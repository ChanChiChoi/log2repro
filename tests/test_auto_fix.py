"""Tests for the auto-fix chain (validators/auto_fix.py)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from log2repro.validators.auto_fix import (
    FixResult,
    _build_fix_suggestions,
    _classify_error,
    _extract_error_snippet,
    auto_fix_loop,
)
from log2repro.validators.sandbox import SandboxResult


# ---------------------------------------------------------------------------
# _classify_error
# ---------------------------------------------------------------------------


class TestClassifyError:
    """Tests for error classification from stderr."""

    def test_syntax_error(self) -> None:
        stderr = '  File "x.py", line 5\n    def f(\n         ^\nSyntaxError: invalid syntax'
        assert _classify_error(stderr) == "SyntaxError"

    def test_module_not_found(self) -> None:
        stderr = "ModuleNotFoundError: No module named 'requests'"
        assert _classify_error(stderr) == "ModuleNotFoundError"

    def test_import_error(self) -> None:
        stderr = "ImportError: cannot import name 'foo' from 'bar'"
        assert _classify_error(stderr) == "ImportError"

    def test_name_error(self) -> None:
        stderr = "NameError: name 'undefined_var' is not defined"
        assert _classify_error(stderr) == "NameError"

    def test_attribute_error(self) -> None:
        stderr = "AttributeError: 'dict' object has no attribute 'foo'"
        assert _classify_error(stderr) == "AttributeError"

    def test_type_error(self) -> None:
        stderr = "TypeError: missing 1 required positional argument: 'x'"
        assert _classify_error(stderr) == "TypeError"

    def test_file_not_found(self) -> None:
        stderr = "FileNotFoundError: [Errno 2] No such file or directory: 'data.json'"
        assert _classify_error(stderr) == "FileNotFoundError"

    def test_non_fixable_error(self) -> None:
        stderr = "ValueError: invalid literal for int()"
        assert _classify_error(stderr) is None

    def test_empty_stderr(self) -> None:
        assert _classify_error("") is None

    def test_original_app_error_not_classified(self) -> None:
        """The original application error (e.g. ValueError) should not be classified as fixable."""
        stderr = (
            'Traceback (most recent call last):\n'
            '  File "reproduce.py", line 10\n'
            '    raise ValueError("test")\n'
            'ValueError: test'
        )
        assert _classify_error(stderr) is None


# ---------------------------------------------------------------------------
# _extract_error_snippet
# ---------------------------------------------------------------------------


class TestExtractErrorSnippet:
    """Tests for error snippet extraction."""

    def test_short_stderr(self) -> None:
        stderr = "line1\nline2\nline3"
        assert _extract_error_snippet(stderr, max_lines=10) == stderr

    def test_long_stderr_truncated(self) -> None:
        lines = [f"line{i}" for i in range(30)]
        stderr = "\n".join(lines)
        snippet = _extract_error_snippet(stderr, max_lines=5)
        assert snippet.endswith("line29")
        assert snippet.count("\n") == 4


# ---------------------------------------------------------------------------
# _build_fix_suggestions
# ---------------------------------------------------------------------------


class TestBuildFixSuggestions:
    """Tests for human-readable repair suggestion generation."""

    def test_module_not_found_suggestion(self) -> None:
        stderr = "ModuleNotFoundError: No module named 'pandas'"
        suggestions = _build_fix_suggestions("ModuleNotFoundError", stderr)
        assert len(suggestions) >= 1
        assert "pandas" in suggestions[0]

    def test_syntax_error_suggestion(self) -> None:
        stderr = '  File "x.py", line 10\n    def f(\nSyntaxError: invalid syntax'
        suggestions = _build_fix_suggestions("SyntaxError", stderr)
        assert any("10" in s for s in suggestions)

    def test_name_error_suggestion(self) -> None:
        stderr = "NameError: name 'my_var' is not defined"
        suggestions = _build_fix_suggestions("NameError", stderr)
        assert any("my_var" in s for s in suggestions)

    def test_type_error_suggestion(self) -> None:
        stderr = "TypeError: missing 1 required positional argument: 'x'"
        suggestions = _build_fix_suggestions("TypeError", stderr)
        assert len(suggestions) >= 1

    def test_file_not_found_suggestion(self) -> None:
        stderr = "FileNotFoundError: No such file: 'data.json'"
        suggestions = _build_fix_suggestions("FileNotFoundError", stderr)
        assert any("mock_data" in s for s in suggestions)

    def test_unknown_error_suggestion(self) -> None:
        suggestions = _build_fix_suggestions("SomeWeirdError", "whatever")
        assert len(suggestions) >= 1


# ---------------------------------------------------------------------------
# auto_fix_loop
# ---------------------------------------------------------------------------


class TestAutoFixLoop:
    """Tests for the full auto-fix loop."""

    MOCK_LLM = "log2repro.validators.auto_fix._call_llm"

    def test_immediate_success(self) -> None:
        """If sandbox reproduces the error on first try, return immediately."""
        files = {"reproduce.py": "raise ValueError('x')", "requirements.txt": "", "mock_data.json": "{}"}
        sandbox_fn = lambda f: SandboxResult(stderr="ValueError: x", exit_code=1, error_reproduced=True)

        result = auto_fix_loop("gpt-4o", "ValueError: x", files, sandbox_fn)
        assert result.success is True
        assert result.rounds_used == 1
        assert result.files == files

    def test_fix_syntax_error(self) -> None:
        """SyntaxError triggers LLM fix; second attempt succeeds."""
        files = {"reproduce.py": "def f(\n  pass", "requirements.txt": "", "mock_data.json": "{}"}
        fixed_files = {"reproduce.py": "raise ValueError('x')", "requirements.txt": "", "mock_data.json": "{}"}

        call_count = 0
        def sandbox_fn(f):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return SandboxResult(
                    stderr='  File "reproduce.py", line 1\n    def f(\nSyntaxError: invalid syntax',
                    exit_code=1,
                    error_reproduced=False,
                )
            return SandboxResult(stderr="ValueError: x", exit_code=1, error_reproduced=True)

        with patch(self.MOCK_LLM, return_value="```reproduce.py\nraise ValueError('x')\n```"):
            result = auto_fix_loop("gpt-4o", "ValueError: x", files, sandbox_fn)

        assert result.success is True
        assert result.rounds_used == 2

    def test_fix_module_not_found(self) -> None:
        """ModuleNotFoundError triggers LLM fix."""
        files = {"reproduce.py": "import nonexistent_xyz\n", "requirements.txt": "", "mock_data.json": "{}"}
        fixed_code = "raise ValueError('test')"

        def sandbox_fn(f):
            if "nonexistent_xyz" in f.get("reproduce.py", ""):
                return SandboxResult(
                    stderr="ModuleNotFoundError: No module named 'nonexistent_xyz'",
                    exit_code=1,
                    error_reproduced=False,
                )
            return SandboxResult(stderr="ValueError: test", exit_code=1, error_reproduced=True)

        with patch(self.MOCK_LLM, return_value=f"```reproduce.py\n{fixed_code}\n```"):
            result = auto_fix_loop("gpt-4o", "ValueError: test", files, sandbox_fn)

        assert result.success is True

    def test_non_fixable_error_stops(self) -> None:
        """Non-fixable errors (e.g. ValueError from app logic) stop the loop."""
        files = {"reproduce.py": "raise ValueError('x')", "requirements.txt": "", "mock_data.json": "{}"}
        sandbox_fn = lambda f: SandboxResult(
            stderr="ValueError: wrong value", exit_code=1, error_reproduced=False,
        )

        result = auto_fix_loop("gpt-4o", "ValueError: x", files, sandbox_fn)
        assert result.success is False
        assert result.degraded is True
        assert result.rounds_used == 1
        assert len(result.suggestions) >= 1

    def test_pip_failure_stops(self) -> None:
        """pip install failure returns immediately with degraded result."""
        files = {"reproduce.py": "import foo", "requirements.txt": "foo>=999", "mock_data.json": "{}"}
        sandbox_fn = lambda f: SandboxResult(
            stderr="ModuleNotFoundError: No module named 'foo'",
            exit_code=1,
            error_reproduced=False,
            pip_ok=False,
        )

        result = auto_fix_loop("gpt-4o", "ValueError: x", files, sandbox_fn)
        assert result.success is False
        assert result.degraded is True
        assert result.rounds_used == 1
        assert any("pip" in s.lower() for s in result.suggestions)

    def test_exhausted_rounds(self) -> None:
        """After MAX_FIX_ROUNDS, returns degraded result."""
        files = {"reproduce.py": "import nonexistent\n", "requirements.txt": "", "mock_data.json": "{}"}
        sandbox_fn = lambda f: SandboxResult(
            stderr="ModuleNotFoundError: No module named 'nonexistent'",
            exit_code=1,
            error_reproduced=False,
        )

        with patch(self.MOCK_LLM, return_value="```reproduce.py\nimport nonexistent\n```"):
            result = auto_fix_loop("gpt-4o", "ValueError: x", files, sandbox_fn)

        assert result.success is False
        assert result.degraded is True
        assert result.rounds_used == 3
        assert len(result.suggestions) >= 1

    def test_llm_call_failure_continues(self) -> None:
        """LLM call failure doesn't crash; loop continues."""
        files = {"reproduce.py": "def f(\n  pass", "requirements.txt": "", "mock_data.json": "{}"}
        sandbox_fn = lambda f: SandboxResult(
            stderr='SyntaxError: invalid syntax', exit_code=1, error_reproduced=False,
        )

        with patch(self.MOCK_LLM, side_effect=RuntimeError("API error")):
            result = auto_fix_loop("gpt-4o", "ValueError: x", files, sandbox_fn)

        assert result.success is False
        assert result.rounds_used == 3

    def test_history_recorded(self) -> None:
        """Each round's error type and snippet are recorded in history."""
        files = {"reproduce.py": "import bad\n", "requirements.txt": "", "mock_data.json": "{}"}
        sandbox_fn = lambda f: SandboxResult(
            stderr="ModuleNotFoundError: No module named 'bad'",
            exit_code=1,
            error_reproduced=False,
        )

        with patch(self.MOCK_LLM, return_value="```reproduce.py\nimport bad\n```"):
            result = auto_fix_loop("gpt-4o", "ValueError: x", files, sandbox_fn)

        assert len(result.history) == 3
        assert all(h[0] == "ModuleNotFoundError" for h in result.history)
