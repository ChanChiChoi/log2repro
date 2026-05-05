"""Root cause analysis generator.

Uses the LLM to perform a structured root cause analysis of an error and
produces fix recommendations ranked by confidence.

Typical usage::

    from log2repro.generators.analysis import generate_analysis
    from log2repro.generators.code_gen import ReproContext

    ctx = ReproContext(trace=parsed_trace, ast_context=ast_ctx, model="gpt-4o")
    result = generate_analysis(ctx)
    print(result.root_cause)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from log2repro.generators.code_gen import ReproContext, _call_llm
from log2repro.generators.prompts import SYSTEM_PROMPT_ANALYSIS, render_analysis_message
from log2repro.models import AnalysisResult, FixRecommendation
from log2repro.parsers.base import ParsedTrace

logger = logging.getLogger(__name__)

# Section names used in the analysis output
_SECTION_NAMES: list[str] = [
    "Root Cause",
    "Error Type",
    "Affected Code Path",
    "Impact",
    "Fix Recommendations",
]

# Pattern to extract individual recommendations with confidence tags
_RE_RECOMMENDATION: re.Pattern[str] = re.compile(
    r"\[(HIGH|MEDIUM|LOW)\]\s*(.*?)(?=\n\[|\Z)", re.DOTALL | re.IGNORECASE
)

# Pattern to extract code snippets within recommendations
_RE_CODE_SNIPPET: re.Pattern[str] = re.compile(
    r"```(?:python)?\s*\n(.*?)```", re.DOTALL
)

# Confidence level ordering for sorting
_CONFIDENCE_ORDER: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


def _extract_section(text: str, name: str) -> str:
    """Extract the content of a Markdown section by name.

    Returns the text between ``## {name}`` and the next ``##`` header
    (or end of string), stripped of leading/trailing whitespace.
    Returns empty string if the section is not found or has no content.
    """
    import re as _re

    # Split text by all ## headers, then find the one matching `name`
    parts = _re.split(r"^## ", text, flags=_re.MULTILINE)
    name_lower = name.lower()
    for part in parts:
        # Each part starts with the header text (after "## ")
        if part.lower().startswith(name_lower):
            # Content is everything after the header line
            content = part[len(name):].lstrip("\n").rstrip()
            return content
    return ""


def _parse_analysis_response(raw_text: str) -> AnalysisResult:
    """Parse the LLM Markdown response into an AnalysisResult.

    Extracts each structured section and parses fix recommendations
    with their confidence levels.
    """
    result = AnalysisResult(raw_markdown=raw_text)

    # Extract sections
    result.root_cause = _extract_section(raw_text, "Root Cause")
    result.error_type = _extract_section(raw_text, "Error Type")
    result.affected_code_path = _extract_section(raw_text, "Affected Code Path")
    result.impact = _extract_section(raw_text, "Impact")

    # Extract recommendations
    recs_text = _extract_section(raw_text, "Fix Recommendations")
    if recs_text:
        for rec_match in _RE_RECOMMENDATION.finditer(recs_text):
            confidence = rec_match.group(1).lower()
            body = rec_match.group(2).strip()

            # Extract code snippet if present
            code_match = _RE_CODE_SNIPPET.search(body)
            code_snippet = code_match.group(1).strip() if code_match else ""

            # Description is the body without the code block
            description = _RE_CODE_SNIPPET.sub("", body).strip()

            result.recommendations.append(
                FixRecommendation(
                    description=description,
                    confidence=confidence,
                    code_snippet=code_snippet,
                )
            )

    # Sort by confidence: high → medium → low
    result.recommendations.sort(
        key=lambda r: _CONFIDENCE_ORDER.get(r.confidence, 99)
    )

    return result


def generate_analysis(
    context: ReproContext,
    *,
    temperature: float = 0.2,
    max_tokens: int = 2048,
    extra_body: dict[str, object] | None = None,
) -> AnalysisResult:
    """Generate a root cause analysis from a :class:`ReproContext`.

    Calls the LLM with an analysis-specific system prompt and parses the
    structured Markdown response into an :class:`AnalysisResult`.

    Args:
        context: Aggregated trace + AST context.
        temperature: LLM sampling temperature.
        max_tokens: Maximum tokens in the LLM response.
        extra_body: Additional parameters passed to the LLM API request body.

    Returns:
        A structured :class:`AnalysisResult`.

    Raises:
        RuntimeError: If the LLM fails after retries.
    """
    system_prompt = SYSTEM_PROMPT_ANALYSIS
    user_message = render_analysis_message(**context.to_prompt_vars())

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    logger.info("Generating root cause analysis (model=%s)", context.model)
    raw_text = _call_llm(
        model=context.model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body=extra_body,
    )

    return _parse_analysis_response(raw_text)


def generate_analysis_markdown(result: AnalysisResult, trace: ParsedTrace) -> str:
    """Generate the content for ``analysis.md``.

    Creates a self-contained Markdown document with the analysis results,
    metadata header, and fix recommendations table.

    Args:
        result: The parsed analysis result.
        trace: The original parsed trace.

    Returns:
        Complete Markdown content for ``analysis.md``.
    """
    # Build recommendations table
    recs_section = ""
    if result.recommendations:
        recs_section = "\n## Fix Recommendations\n\n"
        recs_section += "| # | Confidence | Description |\n"
        recs_section += "|---|------------|-------------|\n"
        for i, rec in enumerate(result.recommendations, 1):
            conf_emoji = {"high": "HIGH", "medium": "MED", "low": "LOW"}.get(
                rec.confidence, rec.confidence.upper()
            )
            desc = rec.description.replace("\n", " ").replace("|", "\\|")
            recs_section += f"| {i} | **{conf_emoji}** | {desc} |\n"

        # Add code snippets below the table
        has_snippets = any(r.code_snippet for r in result.recommendations)
        if has_snippets:
            recs_section += "\n### Code Snippets\n\n"
            for i, rec in enumerate(result.recommendations, 1):
                if rec.code_snippet:
                    recs_section += f"**Fix #{i}** ({rec.confidence.upper()}):\n"
                    recs_section += f"```python\n{rec.code_snippet}\n```\n\n"

    return f"""\
# Root Cause Analysis

## Metadata

- **Error:** `{trace.error}`
- **File:** `{trace.file}:{trace.line}`
- **Analysis model:** auto
- **Generated:** {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}

## Root Cause

{result.root_cause or "*(not determined)*"}

## Error Type

{result.error_type or "*(not determined)*"}

## Affected Code Path

{result.affected_code_path or "*(not determined)*"}

## Impact

{result.impact or "*(not determined)*"}
{recs_section}
---
*Generated by log2repro at {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}*
"""
