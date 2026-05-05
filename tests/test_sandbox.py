"""Tests for the sandbox executor."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from log2repro.validators.sandbox import (
    SandboxResult,
    _check_error_reproduced,
    _extract_exc_type,
    run_in_sandbox,
)


# ---------------------------------------------------------------------------
# _extract_exc_type
# ---------------------------------------------------------------------------


class TestExtractExcType:
    """Unit tests for exception type extraction."""

    def test_simple_exception(self) -> None:
        assert _extract_exc_type("ValueError: bad value") == "ValueError"

    def test_no_colon(self) -> None:
        assert _extract_exc_type("KeyError") == "KeyError"

    def test_dotted_path(self) -> None:
        assert _extract_exc_type("ssl.SSLCertVerificationError: cert expired") == "SSLCertVerificationError"

    def test_deep_dotted_path(self) -> None:
        assert _extract_exc_type("numpy.core._exceptions._UFuncNoLoopError: no loop") == "_UFuncNoLoopError"

    def test_errno_format(self) -> None:
        assert _extract_exc_type("OSError: [Errno 24] Too many open files") == "OSError"

    def test_app_errors_path(self) -> None:
        assert _extract_exc_type("app.api.errors.APIError: 400 - msg") == "APIError"

    def test_empty_string(self) -> None:
        assert _extract_exc_type("") == ""


# ---------------------------------------------------------------------------
# _check_error_reproduced
# ---------------------------------------------------------------------------


class TestCheckErrorReproduced:
    """Unit tests for error reproduction detection."""

    def test_matching_traceback(self) -> None:
        stderr = textwrap.dedent("""\
            Traceback (most recent call last):
              File "reproduce.py", line 10, in <module>
                raise ValueError("bad value")
            ValueError: bad value
        """)
        assert _check_error_reproduced(stderr, "ValueError: bad value") is True

    def test_matching_type_only(self) -> None:
        stderr = "KeyError: 'missing_key'"
        assert _check_error_reproduced(stderr, "KeyError: some key") is True

    def test_no_match(self) -> None:
        stderr = "TypeError: cannot convert"
        assert _check_error_reproduced(stderr, "ValueError: bad value") is False

    def test_empty_stderr(self) -> None:
        assert _check_error_reproduced("", "ValueError: x") is False

    def test_empty_expected_error(self) -> None:
        assert _check_error_reproduced("ValueError: x", "") is False

    def test_dotted_path_in_expected(self) -> None:
        stderr = "requests.exceptions.SSLError: SSL error"
        assert _check_error_reproduced(stderr, "requests.exceptions.SSLError: expired") is True

    def test_substring_match_in_traceback(self) -> None:
        """Exception type appears anywhere in stderr (traceback line)."""
        stderr = textwrap.dedent("""\
            Traceback (most recent call last):
              File "reproduce.py", line 5
            app.errors.StorageError: decompression failed
        """)
        assert _check_error_reproduced(stderr, "app.storage.errors.StorageError: failed") is True


# ---------------------------------------------------------------------------
# run_in_sandbox (real subprocess)
# ---------------------------------------------------------------------------


class TestRunInSandbox:
    """Integration tests that actually run scripts via subprocess."""

    def test_script_that_raises(self, tmp_path: Path) -> None:
        """Script that raises ValueError is detected."""
        script = tmp_path / "reproduce.py"
        script.write_text("raise ValueError('test error')\n")

        result = run_in_sandbox(script, expected_error="ValueError: test error")
        assert result.exit_code != 0
        assert result.error_reproduced is True
        assert "ValueError" in result.stderr
        assert result.timed_out is False

    def test_script_that_succeeds(self, tmp_path: Path) -> None:
        """Script that exits cleanly does not reproduce the error."""
        script = tmp_path / "reproduce.py"
        script.write_text("print('hello')\n")

        result = run_in_sandbox(script, expected_error="ValueError: x")
        assert result.exit_code == 0
        assert result.error_reproduced is False
        assert "hello" in result.stdout

    def test_script_not_found(self, tmp_path: Path) -> None:
        """Missing script returns error."""
        result = run_in_sandbox(tmp_path / "nonexistent.py", expected_error="X")
        assert result.exit_code == 1
        assert result.error_reproduced is False
        assert "not found" in result.stderr.lower() or "not found" in result.stderr

    def test_timeout(self, tmp_path: Path) -> None:
        """Script that hangs is killed after timeout."""
        script = tmp_path / "hang.py"
        script.write_text("import time; time.sleep(60)\n")

        result = run_in_sandbox(script, timeout=1, expected_error="X")
        assert result.timed_out is True
        assert result.exit_code == -1

    def test_captures_stdout_and_stderr(self, tmp_path: Path) -> None:
        """Both stdout and stderr are captured."""
        script = tmp_path / "output.py"
        script.write_text(
            "import sys\n"
            "print('on stdout')\n"
            "print('on stderr', file=sys.stderr)\n"
            "raise RuntimeError('boom')\n"
        )

        result = run_in_sandbox(script, expected_error="RuntimeError: boom")
        assert "on stdout" in result.stdout
        assert "on stderr" in result.stderr
        assert result.error_reproduced is True

    def test_empty_expected_error(self, tmp_path: Path) -> None:
        """Empty expected_error means error_reproduced is always False."""
        script = tmp_path / "err.py"
        script.write_text("raise ValueError('x')\n")

        result = run_in_sandbox(script, expected_error="")
        assert result.error_reproduced is False

    def test_custom_working_directory(self, tmp_path: Path) -> None:
        """Script runs in its own directory (cwd = script parent)."""
        subdir = tmp_path / "sub"
        subdir.mkdir()
        script = subdir / "check_cwd.py"
        script.write_text(
            "import os\n"
            f"expected = {str(subdir)!r}\n"
            "actual = os.getcwd()\n"
            "assert actual == expected, f'{actual} != {expected}'\n"
        )

        result = run_in_sandbox(script, expected_error="")
        assert result.exit_code == 0

    def test_venv_created(self, tmp_path: Path) -> None:
        """Sandbox creates a venv (venv_path is populated)."""
        script = tmp_path / "hello.py"
        script.write_text("print('hello')\n")

        result = run_in_sandbox(script, expected_error="")
        assert result.venv_path != ""
        assert Path(result.venv_path).exists() or result.exit_code == 0

    def test_pip_install_with_requirements(self, tmp_path: Path) -> None:
        """pip install runs when requirements.txt is provided."""
        script = tmp_path / "check.py"
        script.write_text("import pyjokes\nprint(pyjokes.get_joke())\n")
        req = tmp_path / "requirements.txt"
        req.write_text("pyjokes\n")

        result = run_in_sandbox(script, requirements_path=req, expected_error="")
        # pyjokes is a real package — pip install should succeed
        # (but only if network is available; if not, pip_ok will be False)
        assert result.pip_ok is False or result.exit_code == 0

    def test_pip_install_bad_requirement(self, tmp_path: Path) -> None:
        """pip install with nonexistent package reports failure."""
        script = tmp_path / "test.py"
        script.write_text("print('hi')\n")
        req = tmp_path / "requirements.txt"
        req.write_text("nonexistent_package_xyz_99999\n")

        result = run_in_sandbox(script, requirements_path=req, timeout=30, expected_error="")
        # pip should fail, but pip_ok reflects that
        assert result.pip_ok is False or result.exit_code != 0

    def test_empty_requirements_skips_pip(self, tmp_path: Path) -> None:
        """Empty requirements.txt skips pip install."""
        script = tmp_path / "test.py"
        script.write_text("print('ok')\n")
        req = tmp_path / "requirements.txt"
        req.write_text("# just a comment\n\n")

        result = run_in_sandbox(script, requirements_path=req, expected_error="")
        assert result.pip_ok is True
        assert result.exit_code == 0

    def test_network_isolation_env(self, tmp_path: Path) -> None:
        """Sandbox sets NO_PROXY=* to block outbound network."""
        script = tmp_path / "netcheck.py"
        script.write_text(
            "import os\n"
            "assert os.environ.get('NO_PROXY') == '*', 'NO_PROXY not set'\n"
            "assert os.environ.get('http_proxy') == '', 'http_proxy not empty'\n"
        )

        result = run_in_sandbox(script, expected_error="")
        assert result.exit_code == 0
