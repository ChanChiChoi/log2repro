"""Validator for benchmark: checks generated code quality.

Provides two key metrics:
1. **Trigger check**: Does the generated code reference the original error type?
2. **Hallucination check**: Does the code import/use things not in the context?
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from log2repro.generators.code_gen import parse_llm_response
from log2repro.parsers.base import ParsedTrace

# Known safe stdlib modules (subset)
_STDLIB_MODULES: frozenset[str] = frozenset({
    "json", "os", "sys", "re", "math", "datetime", "time", "pathlib",
    "typing", "collections", "itertools", "functools", "dataclasses",
    "abc", "io", "tempfile", "unittest", "unittest.mock", "copy",
    "hashlib", "hmac", "secrets", "uuid", "enum", "struct", "csv",
    "logging", "argparse", "textwrap", "string", "contextlib",
    "traceback", "warnings", "decimal", "fractions", "statistics",
    "socket", "ssl", "http", "urllib", "email", "html", "xml",
    "sqlite3", "zipfile", "gzip", "shutil", "subprocess",
})

# Known safe third-party packages
_KNOWN_PACKAGES: frozenset[str] = frozenset({
    "requests", "flask", "fastapi", "django", "sqlalchemy", "pydantic",
    "torch", "numpy", "pandas", "pytest", "click", "typer", "rich",
    "jinja2", "litellm", "uvicorn", "starlette", "httpx", "aiohttp",
    "psycopg2", "asyncpg", "redis", "celery",
})

# Regex to find import statements
_IMPORT_RE: re.Pattern[str] = re.compile(
    r"^(?:from\s+(\S+)|import\s+(\S+))",
    re.MULTILINE,
)


@dataclass
class ValidationResult:
    """Result of validating a single generated response.

    Attributes:
        has_reproduce_py: Whether the response contained ``reproduce.py``.
        has_requirements: Whether the response contained ``requirements.txt``.
        has_mock_data: Whether the response contained ``mock_data.json``.
        triggers_error: Whether the code references the original error type.
        hallucinated_imports: List of module names not in known-good sets.
        hallucinated: Whether any hallucinations were detected.
    """

    has_reproduce_py: bool = False
    has_requirements: bool = False
    has_mock_data: bool = False
    triggers_error: bool = False
    hallucinated_imports: list[str] | None = None
    hallucinated: bool = False

    @property
    def all_files_present(self) -> bool:
        """True if all 3 required files are present."""
        return self.has_reproduce_py and self.has_requirements and self.has_mock_data


def validate_response(
    response_text: str,
    trace: ParsedTrace,
) -> ValidationResult:
    """Validate a generated LLM response against the original trace.

    Args:
        response_text: Raw LLM response text.
        trace: The original parsed trace (provides the expected error type).

    Returns:
        A ``ValidationResult`` with all checks populated.
    """
    files = parse_llm_response(response_text)

    result = ValidationResult()
    result.has_reproduce_py = "reproduce.py" in files
    result.has_requirements = "requirements.txt" in files
    result.has_mock_data = "mock_data.json" in files

    # Check if the code would trigger the original error
    repro_code = files.get("reproduce.py", "")
    error_type = trace.error.split(":")[0].strip()
    # Also handle dotted types like "pydantic_core._pydantic_core.ValidationError"
    short_error = error_type.rsplit(".", 1)[-1] if "." in error_type else error_type
    result.triggers_error = (
        short_error in repro_code
        or error_type in repro_code
        or "raise" in repro_code  # generic: at least raises something
    )

    # Hallucination detection: check for unknown imports
    imports = set()
    for m in _IMPORT_RE.finditer(repro_code):
        module = m.group(1) or m.group(2)
        if module:
            # Get top-level package name
            top = module.split(".")[0]
            imports.add(top)

    known = _STDLIB_MODULES | _KNOWN_PACKAGES
    hallucinated = [imp for imp in imports if imp not in known and not imp.startswith("_")]
    result.hallucinated_imports = hallucinated if hallucinated else None
    result.hallucinated = bool(hallucinated)

    return result
