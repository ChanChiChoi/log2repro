"""LLM-driven reproduction code generator.

Uses ``litellm.completion()`` to call any supported LLM backend and parses
the Markdown response into individual files (``reproduce.py``,
``requirements.txt``, ``mock_data.json``).

Typical usage::

    from log2repro.generators.code_gen import ReproContext, generate_repro_script

    ctx = ReproContext(trace=parsed_trace, ast_context=ast_ctx, model="gpt-4o")
    files = generate_repro_script(ctx)
    for name, content in files.items():
        Path(name).write_text(content)
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from log2repro.extractors.ast_parser import ASTContext
from log2repro.generators.prompts import (
    render_refine_message,
    render_user_message,
    select_system_prompt,
)
from log2repro.parsers.base import ParsedTrace
from log2repro.validators.sandbox import SandboxResult, run_in_sandbox

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

DEFAULT_TEMPERATURE: float = 0.2
DEFAULT_MAX_TOKENS: int = 2000
MAX_RETRIES: int = 2
RETRY_BACKOFF_BASE: float = 2.0  # seconds; exponential backoff
DEFAULT_SANDBOX_TIMEOUT: int = 10  # seconds
DEFAULT_MAX_REFINE_ROUNDS: int = 2  # max sandbox→LLM refinement cycles

# Expected output filenames
EXPECTED_FILES: tuple[str, ...] = ("reproduce.py", "requirements.txt", "mock_data.json")

# Pattern that matches a Markdown fenced code block with a filename hint.
# Captures the block name (e.g. "reproduce.py") and the code body.
_CODE_BLOCK_RE: re.Pattern[str] = re.compile(
    r"```(?P<name>[^\n`]*)\n(?P<code>.*?)```",
    re.DOTALL,
)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ReproContext:
    """Aggregated context for reproduction script generation.

    Combines parsed trace information with AST-extracted source context
    to provide the LLM with all necessary information.

    Attributes:
        trace: Parsed traceback information.
        ast_context: AST-extracted source context (may be empty).
        model: LLM model identifier (e.g. ``"gpt-4o"``, ``"claude-3-opus"``).
    """

    trace: ParsedTrace
    ast_context: ASTContext = field(default_factory=ASTContext)
    model: str = "gpt-4o"

    def to_prompt_vars(self) -> dict[str, Any]:
        """Return a dict suitable for Jinja2 template rendering."""
        return {
            "file": self.trace.file,
            "line": self.trace.line,
            "error": self.trace.error,
            "chain": self.trace.chain,
            "context_vars": self.trace.context_vars,
            "signature": self.ast_context.signature,
            "imports": self.ast_context.imports,
            "known_vars": self.ast_context.known_vars,
        }


# ---------------------------------------------------------------------------
# LLM call helper (isolated for easy mocking)
# ---------------------------------------------------------------------------


def _call_llm(
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
) -> str:
    """Call the LLM and return the raw response text.

    This is the only function that touches ``litellm`` — isolate it so
    tests can mock this single entry point without needing ``litellm``
    installed.

    Args:
        model: LLM model identifier.
        messages: Chat messages (system + user).
        temperature: Sampling temperature.
        max_tokens: Maximum response tokens.

    Returns:
        The raw text content of the LLM response.
    """
    import litellm

    response = litellm.completion(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Internal: initial generation
# ---------------------------------------------------------------------------


def _generate_initial(
    context: ReproContext,
    *,
    temperature: float,
    max_tokens: int,
) -> dict[str, str]:
    """Call the LLM to produce the first draft of reproduction files.

    Retries on transient failures up to :data:`MAX_RETRIES` times.
    """
    system_prompt = select_system_prompt(context.trace.error)
    user_message = render_user_message(**context.to_prompt_vars())

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 2):  # attempt 1, 2, 3
        try:
            logger.info(
                "LLM call attempt %d/%d (model=%s)",
                attempt,
                MAX_RETRIES + 1,
                context.model,
            )
            raw_text = _call_llm(
                model=context.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            files = parse_llm_response(raw_text)
            _validate_files(files)
            logger.info("LLM call succeeded on attempt %d", attempt)
            return files

        except Exception as exc:
            last_error = exc
            logger.warning(
                "LLM call failed on attempt %d: %s",
                attempt,
                exc,
            )
            if attempt <= MAX_RETRIES:
                wait = RETRY_BACKOFF_BASE ** attempt
                logger.info("Retrying in %.1f seconds...", wait)
                time.sleep(wait)

    raise RuntimeError(
        f"LLM generation failed after {MAX_RETRIES + 1} attempts. "
        f"Last error: {last_error}"
    ) from last_error


# ---------------------------------------------------------------------------
# Internal: sandbox feedback loop
# ---------------------------------------------------------------------------


def _run_sandbox_check(
    files: dict[str, str],
    context: ReproContext,
    *,
    timeout: int,
) -> SandboxResult:
    """Write *files* to a temp dir and run ``reproduce.py`` in the sandbox."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="log2repro_") as tmpdir:
        tmp = Path(tmpdir)
        tmp = Path(tmpdir)
        for name, content in files.items():
            (tmp / name).write_text(content)

        return run_in_sandbox(
            script_path=tmp / "reproduce.py",
            requirements_path=tmp / "requirements.txt" if "requirements.txt" in files else None,
            timeout=timeout,
            expected_error=context.trace.error,
        )


def _refine_with_sandbox_feedback(
    context: ReproContext,
    *,
    current_files: dict[str, str],
    sandbox_result: SandboxResult,
    temperature: float,
    max_tokens: int,
) -> dict[str, str]:
    """Ask the LLM to fix ``reproduce.py`` based on sandbox output.

    Builds a refinement prompt that includes the current code and the
    sandbox stderr, then calls the LLM for a targeted fix.
    """
    from log2repro.validators.sandbox import _extract_exc_type

    refine_user_msg = render_refine_message(
        original_error=context.trace.error,
        exc_type=_extract_exc_type(context.trace.error),
        file=context.trace.file,
        line=context.trace.line,
        exit_code=sandbox_result.exit_code,
        timed_out=sandbox_result.timed_out,
        stderr=sandbox_result.stderr,
        stdout=sandbox_result.stdout,
        current_code=current_files.get("reproduce.py", ""),
    )

    # Use the same system prompt as the initial generation
    system_prompt = select_system_prompt(context.trace.error)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": refine_user_msg},
    ]

    raw_text = _call_llm(
        model=context.model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    # Parse the LLM response — may only return the updated reproduce.py
    new_files = parse_llm_response(raw_text)
    if "reproduce.py" in new_files:
        # Merge: update reproduce.py, keep requirements.txt and mock_data.json
        merged = {**current_files, **new_files}
        return merged

    # If LLM didn't return a reproduce.py block, keep the original files
    logger.warning("Refinement LLM response did not contain a reproduce.py block")
    return current_files


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_repro_script(
    context: ReproContext,
    *,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    sandbox_timeout: int = DEFAULT_SANDBOX_TIMEOUT,
    max_refine_rounds: int = DEFAULT_MAX_REFINE_ROUNDS,
) -> dict[str, str]:
    """Generate a reproduction script from a :class:`ReproContext`.

    Assembles the system + user prompts, calls the LLM via
    ``litellm.completion()``, and parses the response into individual files.
    On failure, retries up to :data:`MAX_RETRIES` times with exponential
    backoff.

    After a successful generation, runs the script in a sandbox to verify
    it reproduces the original error.  If not, feeds the sandbox stderr
    back to the LLM for targeted refinement (up to *max_refine_rounds*
    times).

    Args:
        context: Aggregated trace + AST context.
        temperature: LLM sampling temperature.
        max_tokens: Maximum tokens in the LLM response.
        sandbox_timeout: Seconds before sandbox kills the script.
        max_refine_rounds: Max sandbox→LLM feedback loops (0 to skip).

    Returns:
        A dict mapping filenames to their contents, e.g.::

            {
                "reproduce.py": "...",
                "requirements.txt": "...",
                "mock_data.json": "...",
            }

    Raises:
        RuntimeError: If the LLM fails after all retries.
    """
    # --- Step 1: initial LLM generation with retry ---
    files = _generate_initial(context, temperature=temperature, max_tokens=max_tokens)

    # --- Step 2: sandbox verification + refinement loop ---
    if max_refine_rounds <= 0:
        return files

    for round_idx in range(1, max_refine_rounds + 1):
        result = _run_sandbox_check(files, context, timeout=sandbox_timeout)
        if result.error_reproduced:
            logger.info("Sandbox reproduced the original error on round %d", round_idx)
            return files

        logger.info(
            "Sandbox round %d: error NOT reproduced (exit=%d, timed_out=%s). "
            "Refining...",
            round_idx,
            result.exit_code,
            result.timed_out,
        )

        # Feed sandbox output back to LLM for a targeted fix
        files = _refine_with_sandbox_feedback(
            context,
            current_files=files,
            sandbox_result=result,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    logger.info("Refinement exhausted after %d rounds, returning last result", max_refine_rounds)
    return files


def parse_llm_response(response_text: str) -> dict[str, str]:
    """Parse an LLM response containing Markdown code blocks into files.

    Looks for fenced code blocks with filename hints such as:

        ```reproduce.py
        ...
        ```

    Also handles plain ``python`` / ``json`` / ``text`` language tags by
    mapping them to the expected filename when possible.

    Args:
        response_text: Raw LLM response text.

    Returns:
        A dict mapping filenames to their contents.
    """
    files: dict[str, str] = {}
    for match in _CODE_BLOCK_RE.finditer(response_text):
        raw_name = match.group("name").strip()
        code = match.group("code").strip()
        name = _normalise_block_name(raw_name)
        if name:
            files[name] = code
    return files


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Mapping from language tags to filenames when the LLM uses ```python etc.
_LANG_TO_FILENAME: dict[str, str] = {
    "python": "reproduce.py",
    "py": "reproduce.py",
    "json": "mock_data.json",
    "text": "requirements.txt",
    "txt": "requirements.txt",
    "": "requirements.txt",  # bare ``` with no tag → assume requirements
}


def _normalise_block_name(raw: str) -> str | None:
    """Normalise a code-block name to one of the expected filenames.

    Returns ``None`` if the block should be ignored (e.g. an unrelated
    language tag like ``sql``).
    """
    lower = raw.lower().strip()

    # Already a known filename
    if lower in EXPECTED_FILES:
        return lower

    # Map language tags
    if lower in _LANG_TO_FILENAME:
        return _LANG_TO_FILENAME[lower]

    # If it looks like a filename (contains a dot), keep it
    if "." in raw:
        return raw.strip()

    return None


def _validate_files(files: dict[str, str]) -> None:
    """Raise if the parsed response is missing required files."""
    missing = [f for f in EXPECTED_FILES if f not in files]
    if missing:
        raise ValueError(
            f"LLM response missing required file(s): {', '.join(missing)}. "
            f"Got: {list(files.keys())}"
        )
