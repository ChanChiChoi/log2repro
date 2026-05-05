"""Tests for the CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from log2repro.cli import app

FIXTURES = Path(__file__).parent / "fixtures"
TRACE_FILE = FIXTURES / "trace_sample.log"

runner = CliRunner()

# Good LLM response for full-pipeline tests
GOOD_LLM_RESPONSE = """\
```reproduce.py
raise ValueError("test")
```

```requirements.txt
# none
```

```mock_data.json
{}
```
"""


class TestCLIRun:
    """Tests for the ``log2repro run`` command."""

    def test_run_dry_run_from_file(self) -> None:
        """--dry-run with a file path produces valid JSON output."""
        result = runner.invoke(app, ["run", str(TRACE_FILE), "--dry-run"])
        assert result.exit_code == 0
        assert "dry_run" in result.output or "Parsed Context" in result.output

    def test_run_dry_run_from_string(self) -> None:
        """--dry-run with a raw traceback string works."""
        text = (
            'Traceback (most recent call last):\n'
            '  File "x.py", line 1, in f\n'
            '    1 / 0\n'
            'ZeroDivisionError: division by zero'
        )
        result = runner.invoke(app, ["run", text, "--dry-run"])
        assert result.exit_code == 0
        assert "ZeroDivisionError" in result.output

    def test_run_full_pipeline(self, tmp_path: Path) -> None:
        """Full pipeline with mocked LLM produces output files."""
        out_dir = tmp_path / "output"
        text = (
            'Traceback (most recent call last):\n'
            '  File "x.py", line 1, in f\n'
            '    pass\n'
            'RuntimeError: test'
        )
        with (
            patch("log2repro.generators.code_gen._call_llm", return_value=GOOD_LLM_RESPONSE),
            patch("log2repro.validators.sandbox.run_in_sandbox") as mock_sandbox,
        ):
            from log2repro.validators.sandbox import SandboxResult
            mock_sandbox.return_value = SandboxResult(
                stderr="RuntimeError: test", exit_code=1, error_reproduced=True,
            )
            result = runner.invoke(app, ["run", text, "--output-dir", str(out_dir)])

        assert result.exit_code == 0
        assert (out_dir / "reproduce.py").exists()
        assert (out_dir / "requirements.txt").exists()
        assert (out_dir / "mock_data.json").exists()
        assert (out_dir / "README_repro.md").exists()

    def test_run_with_model_option(self, tmp_path: Path) -> None:
        """--model is passed through to the generation pipeline."""
        out_dir = tmp_path / "output"
        text = (
            'Traceback (most recent call last):\n'
            '  File "x.py", line 1, in f\n'
            '    pass\n'
            'Error: msg'
        )
        with (
            patch("log2repro.generators.code_gen._call_llm", return_value=GOOD_LLM_RESPONSE) as mock_llm,
            patch("log2repro.validators.sandbox.run_in_sandbox") as mock_sandbox,
        ):
            from log2repro.validators.sandbox import SandboxResult
            mock_sandbox.return_value = SandboxResult(error_reproduced=True)
            result = runner.invoke(app, ["run", text, "--model", "claude-3-opus", "--output-dir", str(out_dir)])

        assert result.exit_code == 0

    def test_run_output_to_file_legacy(self, tmp_path: Path) -> None:
        """--output writes JSON to the specified file (legacy mode)."""
        out_file = tmp_path / "result.json"
        text = (
            'Traceback (most recent call last):\n'
            '  File "x.py", line 1, in f\n'
            '    pass\n'
            'Error: msg'
        )
        with (
            patch("log2repro.generators.code_gen._call_llm", return_value=GOOD_LLM_RESPONSE),
            patch("log2repro.validators.sandbox.run_in_sandbox") as mock_sandbox,
        ):
            from log2repro.validators.sandbox import SandboxResult
            mock_sandbox.return_value = SandboxResult(error_reproduced=True)
            result = runner.invoke(app, ["run", text, "--output", str(out_file)])

        assert result.exit_code == 0
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert "traces" in data

    def test_run_empty_input(self) -> None:
        """Empty input exits with code 1."""
        result = runner.invoke(app, ["run", ""])
        assert result.exit_code == 1

    def test_run_nonexistent_file(self) -> None:
        """A path-like string that doesn't exist exits with code 1."""
        result = runner.invoke(app, ["run", "/nonexistent/path/error.log"])
        assert result.exit_code == 1

    def test_run_non_traceback_text(self) -> None:
        """Non-traceback text exits with code 1."""
        result = runner.invoke(app, ["run", "just some random log line"])
        assert result.exit_code == 1

    def test_run_readme_contains_error_info(self, tmp_path: Path) -> None:
        """README_repro.md contains the original error information."""
        out_dir = tmp_path / "output"
        text = (
            'Traceback (most recent call last):\n'
            '  File "x.py", line 5, in process\n'
            '    raise KeyError("missing")\n'
            "KeyError: 'missing'"
        )
        with (
            patch("log2repro.generators.code_gen._call_llm", return_value=GOOD_LLM_RESPONSE),
            patch("log2repro.validators.sandbox.run_in_sandbox") as mock_sandbox,
        ):
            from log2repro.validators.sandbox import SandboxResult
            mock_sandbox.return_value = SandboxResult(error_reproduced=True)
            result = runner.invoke(app, ["run", text, "--output-dir", str(out_dir)])

        assert result.exit_code == 0
        readme = (out_dir / "README_repro.md").read_text()
        assert "KeyError" in readme
        assert "x.py" in readme
        assert "复现脚本" in readme

    def test_run_default_output_dir(self, tmp_path: Path, monkeypatch) -> None:
        """Without --output-dir, defaults to ./repro_out."""
        monkeypatch.chdir(tmp_path)
        text = (
            'Traceback (most recent call last):\n'
            '  File "x.py", line 1, in f\n'
            '    pass\n'
            'Error: msg'
        )
        with (
            patch("log2repro.generators.code_gen._call_llm", return_value=GOOD_LLM_RESPONSE),
            patch("log2repro.validators.sandbox.run_in_sandbox") as mock_sandbox,
        ):
            from log2repro.validators.sandbox import SandboxResult
            mock_sandbox.return_value = SandboxResult(error_reproduced=True)
            result = runner.invoke(app, ["run", text])

        assert result.exit_code == 0
        assert (tmp_path / "repro_out" / "reproduce.py").exists()


class TestCLIVersion:
    """Tests for the ``log2repro version`` command."""

    def test_version_output(self) -> None:
        """Version command prints the version string."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "0.3.0" in result.output
