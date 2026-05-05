"""Evaluation metrics for generated reproduction scripts.

Computes four quality metrics over a batch of generation results:

1. **代码可运行率** (runnable_rate): Does ``reproduce.py`` execute without
   import / syntax errors?
2. **依赖冲突率** (dep_conflict_rate): Does ``requirements.txt`` contain
   unparsable or conflicting version pins?
3. **Mock 覆盖率** (mock_coverage): Are external calls (network, DB, FS)
   properly mocked rather than hitting real services?
4. **Token 效率** (token_efficiency): Errors reproduced per 1 000 tokens
   consumed.

Typical usage::

    from log2repro.eval_metrics import EvalResult, evaluate_batch

    results = evaluate_batch(generation_results)
    print(results.report())
"""

from __future__ import annotations

import ast
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from log2repro.generators.code_gen import parse_llm_response
from log2repro.validators.sandbox import SandboxResult, _extract_exc_type, run_in_sandbox

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Modules whose real usage should be mocked in reproduction scripts
_NETWORK_MODULES: frozenset[str] = frozenset({
    "requests", "httpx", "aiohttp", "http.client", "urllib", "urllib3",
    "socket", "ssl",
})

_DATABASE_MODULES: frozenset[str] = frozenset({
    "sqlalchemy", "psycopg2", "asyncpg", "sqlite3", "django.db",
    "redis", "pymongo",
})

# Regex for ``pip install``-style requirement lines
_REQ_LINE_RE: re.Pattern[str] = re.compile(
    r"^(?P<pkg>[A-Za-z0-9_-]+)\s*(?P<op>[><=!~]{1,3})\s*(?P<ver>\S+)?",
    re.MULTILINE,
)

# Regex for bare ``import`` / ``from ... import`` statements
_IMPORT_RE: re.Pattern[str] = re.compile(
    r"^(?:from\s+(\S+)|import\s+(\S+))",
    re.MULTILINE,
)

# Patterns that indicate a real (non-mocked) network / DB call
_REAL_CALL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"requests\.(get|post|put|delete|patch|head|options)\s*\("),
    re.compile(r"httpx\.(get|post|put|delete|patch|head|options|Client)\s*\("),
    re.compile(r"aiohttp\.ClientSession\(\)"),
    re.compile(r"urllib\.request\.urlopen\s*\("),
    re.compile(r"socket\.create_connection\s*\("),
    re.compile(r"sqlite3\.connect\s*\([^:)]+\)"),  # non-":memory:" connect
    re.compile(r"create_engine\s*\([^)]+['\"](?:postgresql|mysql|sqlite)://"),
    re.compile(r"psycopg2\.connect\s*\("),
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SingleEvalResult:
    """Evaluation result for one generated reproduction script.

    Attributes:
        trace_name: Identifier for the source trace.
        runnable: Whether ``reproduce.py`` executed without import/syntax errors.
        runnable_error: Error message if not runnable.
        dep_conflict: Whether ``requirements.txt`` has conflicts or parse errors.
        dep_conflict_detail: Description of the conflict.
        mock_coverage: Fraction of external calls that are mocked (0.0–1.0).
        unmocked_calls: List of unmocked external call patterns found.
        tokens_used: LLM tokens consumed for this generation.
        error_reproduced: Whether the sandbox reproduced the original error.
    """

    trace_name: str = ""
    runnable: bool = False
    runnable_error: str = ""
    dep_conflict: bool = False
    dep_conflict_detail: str = ""
    mock_coverage: float = 0.0
    unmocked_calls: list[str] = field(default_factory=list)
    tokens_used: int = 0
    error_reproduced: bool = False


@dataclass
class BatchEvalResult:
    """Aggregated evaluation results for a batch of generations.

    Provides computed rate properties and a Markdown report method.
    """

    results: list[SingleEvalResult] = field(default_factory=list)

    # -- Aggregate rates ---------------------------------------------------

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def runnable_rate(self) -> float:
        """代码可运行率: fraction of scripts that ran without import/syntax errors."""
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.runnable) / len(self.results)

    @property
    def dep_conflict_rate(self) -> float:
        """依赖冲突率: fraction of scripts with requirements.txt issues."""
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.dep_conflict) / len(self.results)

    @property
    def mock_coverage(self) -> float:
        """Mock 覆盖率: average mock coverage across all scripts."""
        if not self.results:
            return 0.0
        return sum(r.mock_coverage for r in self.results) / len(self.results)

    @property
    def token_efficiency(self) -> float:
        """Token 效率: errors reproduced per 1 000 tokens."""
        total_tokens = sum(r.tokens_used for r in self.results)
        if total_tokens == 0:
            return 0.0
        reproduced = sum(1 for r in self.results if r.error_reproduced)
        return reproduced / total_tokens * 1000

    @property
    def error_reproduced_rate(self) -> float:
        """错误复现率: fraction of scripts that reproduced the original error."""
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.error_reproduced) / len(self.results)

    # -- Reporting ---------------------------------------------------------

    def report(self) -> str:
        """Generate a Markdown summary table."""
        lines = [
            "# 评估报告",
            "",
            "| 指标 | 值 |",
            "|------|----|",
            f"| 样本数 | {self.total} |",
            f"| 代码可运行率 ↑ | {self.runnable_rate:.1%} |",
            f"| 依赖冲突率 ↓ | {self.dep_conflict_rate:.1%} |",
            f"| Mock 覆盖率 ↑ | {self.mock_coverage:.1%} |",
            f"| Token 效率 ↑ | {self.token_efficiency:.3f} /1ktok |",
            f"| 错误复现率 ↑ | {self.error_reproduced_rate:.1%} |",
            "",
        ]

        # Detail table for scripts that failed
        failures = [r for r in self.results if not r.runnable or r.dep_conflict or r.unmocked_calls]
        if failures:
            lines.append("## 问题明细")
            lines.append("")
            lines.append("| 样本 | 可运行 | 依赖冲突 | 未Mock调用 | 问题描述 |")
            lines.append("|------|--------|----------|-----------|----------|")
            for r in failures:
                runnable = "✓" if r.runnable else "✗"
                dep = "✓" if r.dep_conflict else ""
                unmocked = ", ".join(r.unmocked_calls[:3]) if r.unmocked_calls else ""
                detail = r.runnable_error or r.dep_conflict_detail or ""
                if len(detail) > 60:
                    detail = detail[:57] + "..."
                lines.append(
                    f"| {r.trace_name} | {runnable} | {dep} | {unmocked} | {detail} |"
                )
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Individual metric evaluators
# ---------------------------------------------------------------------------


def check_runnable(
    files: dict[str, str],
    *,
    timeout: int = 10,
) -> tuple[bool, str]:
    """Check whether ``reproduce.py`` can execute without import/syntax errors.

    Writes the files to a temporary directory and runs the script via the
    sandbox.  A script is considered *runnable* if the exit code is 0 **or**
    the stderr contains only the expected application-level exception (i.e.
    no ``ImportError``, ``ModuleNotFoundError``, ``SyntaxError``).

    Returns:
        ``(runnable, error_detail)``
    """
    repro_code = files.get("reproduce.py", "")
    if not repro_code:
        return False, "reproduce.py not found"

    with tempfile.TemporaryDirectory(prefix="log2repro_eval_") as tmpdir:
        tmp = Path(tmpdir)
        for name, content in files.items():
            (tmp / name).write_text(content)

        result = run_in_sandbox(
            script_path=tmp / "reproduce.py",
            requirements_path=tmp / "requirements.txt" if "requirements.txt" in files else None,
            timeout=timeout,
            expected_error="",  # don't suppress any errors
        )

    if result.exit_code == 0:
        return True, ""

    stderr = result.stderr

    # Fatal infrastructure errors → not runnable
    fatal_patterns = [
        "ModuleNotFoundError",
        "ImportError",
        "SyntaxError",
        "IndentationError",
        "NameError",
        "AttributeError",
    ]
    for pattern in fatal_patterns:
        if pattern in stderr:
            # Extract the specific line
            for line in stderr.splitlines():
                if pattern in line:
                    return False, line.strip()
            return False, pattern

    # Timeout is not a code error per se
    if result.timed_out:
        return True, ""

    # Other errors (e.g. the expected application exception) → runnable
    return True, ""


def check_dep_conflict(
    requirements_text: str,
) -> tuple[bool, str]:
    """Check ``requirements.txt`` for parse errors or version conflicts.

    A *conflict* is defined as:
    - Unparseable line (not a valid ``pkg`` or ``pkg>=ver`` spec).
    - Duplicate package with incompatible version pins.

    Returns:
        ``(has_conflict, detail)``
    """
    if not requirements_text or not requirements_text.strip():
        return False, ""

    lines = requirements_text.strip().splitlines()
    seen: dict[str, str] = {}  # pkg → version spec
    issues: list[str] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue

        m = _REQ_LINE_RE.match(line)
        if not m:
            issues.append(f"unparseable: {line!r}")
            continue

        pkg = m.group("pkg").lower().replace("-", "_")
        ver = m.group("op") + (m.group("ver") or "")

        if pkg in seen and seen[pkg] != ver:
            issues.append(f"conflict: {pkg} has {seen[pkg]} and {ver}")
        else:
            seen[pkg] = ver

    if issues:
        return True, "; ".join(issues)
    return False, ""


def check_mock_coverage(
    repro_code: str,
) -> tuple[float, list[str]]:
    """Check how many external calls are properly mocked.

    Scans ``reproduce.py`` for patterns indicating real network / DB / FS
    calls (e.g. ``requests.get(``, ``sqlite3.connect("real.db")``).  Calls
    that appear inside a ``with patch(...)`` block, or on lines containing
    ``side_effect`` / ``return_value`` / ``patch(``, are considered mocked.

    Returns:
        ``(coverage_ratio, list_of_unmocked_patterns)``
    """
    if not repro_code:
        return 1.0, []

    # Find all real-call patterns
    real_calls: list[str] = []
    for pat in _REAL_CALL_PATTERNS:
        for m in pat.finditer(repro_code):
            real_calls.append(m.group())

    if not real_calls:
        return 1.0, []

    # Check if the code uses mock/patch at all
    uses_mock = (
        "unittest.mock" in repro_code
        or "mock.patch" in repro_code
        or "MagicMock" in repro_code
        or "patch(" in repro_code
        or "side_effect" in repro_code
    )

    if not uses_mock:
        return 0.0, real_calls

    # Track ``with patch(...)`` depth to detect mocked blocks
    lines = repro_code.splitlines()
    mock_indent: int | None = None  # indentation level of the ``with patch`` line
    unmocked: list[str] = []

    for call in real_calls:
        found = False
        for i, line in enumerate(lines):
            if call not in line:
                # Track ``with patch(...)`` blocks by indent
                continue
            stripped = line.strip()
            # Lines that are clearly mock setup / definition
            if (
                "side_effect" in stripped
                or "return_value" in stripped
                or stripped.startswith("#")
                or stripped.startswith("def ")
                or "patch(" in stripped
            ):
                found = True
                break

            # Check if this line is inside a ``with patch(...)`` block
            # by scanning upward for the nearest ``with patch`` line
            call_indent = len(line) - len(line.lstrip())
            inside_mock = False
            for j in range(i - 1, -1, -1):
                prev = lines[j]
                if not prev.strip():
                    continue
                prev_indent = len(prev) - len(prev.lstrip())
                if prev_indent >= call_indent:
                    continue
                # This is the enclosing block line
                if "patch(" in prev and "with" in prev:
                    inside_mock = True
                break

            if inside_mock:
                found = True
                break

            # If not inside a mock block, it's unmocked
            unmocked.append(call)
            found = True
            break

    if not real_calls:
        return 1.0, []

    coverage = 1.0 - len(unmocked) / len(real_calls)
    return max(0.0, min(1.0, coverage)), unmocked


# ---------------------------------------------------------------------------
# Batch evaluation
# ---------------------------------------------------------------------------


@dataclass
class GenerationInput:
    """Input for batch evaluation: one generation result.

    Attributes:
        trace_name: Identifier for the source trace.
        files: Generated files (output of ``generate_repro_script``).
        tokens_used: LLM tokens consumed.
        expected_error: The original error string (for sandbox check).
    """

    trace_name: str
    files: dict[str, str]
    tokens_used: int = 0
    expected_error: str = ""


def evaluate_single(
    gen: GenerationInput,
    *,
    sandbox_timeout: int = 10,
) -> SingleEvalResult:
    """Evaluate a single generation result across all four metrics."""
    result = SingleEvalResult(
        trace_name=gen.trace_name,
        tokens_used=gen.tokens_used,
    )

    # 1. 代码可运行率
    result.runnable, result.runnable_error = check_runnable(
        gen.files, timeout=sandbox_timeout,
    )

    # 2. 依赖冲突率
    result.dep_conflict, result.dep_conflict_detail = check_dep_conflict(
        gen.files.get("requirements.txt", ""),
    )

    # 3. Mock 覆盖率
    result.mock_coverage, result.unmocked_calls = check_mock_coverage(
        gen.files.get("reproduce.py", ""),
    )

    # 4. 错误复现 (for token efficiency)
    if gen.expected_error and "reproduce.py" in gen.files:
        with tempfile.TemporaryDirectory(prefix="log2repro_eval_") as tmpdir:
            tmp = Path(tmpdir)
            for name, content in gen.files.items():
                (tmp / name).write_text(content)
            sb = run_in_sandbox(
                script_path=tmp / "reproduce.py",
                timeout=sandbox_timeout,
                expected_error=gen.expected_error,
            )
        result.error_reproduced = sb.error_reproduced

    return result


def evaluate_batch(
    inputs: list[GenerationInput],
    *,
    sandbox_timeout: int = 10,
) -> BatchEvalResult:
    """Evaluate a batch of generation results.

    Args:
        inputs: One :class:`GenerationInput` per generation.
        sandbox_timeout: Seconds before sandbox kills a script.

    Returns:
        A :class:`BatchEvalResult` with aggregate metrics and a report.
    """
    results = [
        evaluate_single(gen, sandbox_timeout=sandbox_timeout)
        for gen in inputs
    ]
    return BatchEvalResult(results=results)
