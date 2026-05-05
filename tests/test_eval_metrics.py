"""Tests for eval_metrics — the four quality metrics."""

from __future__ import annotations

import pytest

from log2repro.eval_metrics import (
    BatchEvalResult,
    GenerationInput,
    SingleEvalResult,
    check_dep_conflict,
    check_mock_coverage,
    check_runnable,
    evaluate_batch,
    evaluate_single,
)


# ---------------------------------------------------------------------------
# check_runnable
# ---------------------------------------------------------------------------


class TestCheckRunnable:
    """Tests for the code-runnability checker."""

    def test_valid_script(self, tmp_path) -> None:
        files = {"reproduce.py": "print('hello')\n"}
        runnable, err = check_runnable(files)
        assert runnable is True
        assert err == ""

    def test_syntax_error(self) -> None:
        files = {"reproduce.py": "def f(\n  pass\n"}
        runnable, err = check_runnable(files)
        assert runnable is False
        assert "SyntaxError" in err

    def test_import_error(self) -> None:
        files = {"reproduce.py": "import nonexistent_module_xyz_12345\n"}
        runnable, err = check_runnable(files)
        assert runnable is False
        assert "ModuleNotFoundError" in err

    def test_missing_reproduce_py(self) -> None:
        files = {"requirements.txt": ""}
        runnable, err = check_runnable(files)
        assert runnable is False
        assert "not found" in err

    def test_app_exception_is_runnable(self) -> None:
        """An application-level exception (e.g. ValueError) means the script IS runnable."""
        files = {"reproduce.py": "raise ValueError('test')\n"}
        runnable, err = check_runnable(files)
        assert runnable is True

    def test_name_error_not_runnable(self) -> None:
        files = {"reproduce.py": "print(undefined_var)\n"}
        runnable, err = check_runnable(files)
        assert runnable is False
        assert "NameError" in err


# ---------------------------------------------------------------------------
# check_dep_conflict
# ---------------------------------------------------------------------------


class TestCheckDepConflict:
    """Tests for requirements.txt conflict detection."""

    def test_empty_requirements(self) -> None:
        has_conflict, detail = check_dep_conflict("")
        assert has_conflict is False

    def test_valid_requirements(self) -> None:
        text = "requests>=2.28\nflask==2.3.0\nnumpy>=1.24\n"
        has_conflict, _ = check_dep_conflict(text)
        assert has_conflict is False

    def test_version_conflict(self) -> None:
        text = "requests>=2.28\nrequests<2.0\n"
        has_conflict, detail = check_dep_conflict(text)
        assert has_conflict is True
        assert "conflict" in detail

    def test_unparseable_line(self) -> None:
        text = "requests>=2.28\nthis is not a valid requirement\n"
        has_conflict, detail = check_dep_conflict(text)
        assert has_conflict is True
        assert "unparseable" in detail

    def test_comments_ignored(self) -> None:
        text = "# this is a comment\nrequests>=2.28\n# another comment\n"
        has_conflict, _ = check_dep_conflict(text)
        assert has_conflict is False

    def test_editable_flags_ignored(self) -> None:
        text = "-e git+https://github.com/foo/bar.git#egg=bar\nrequests>=2.0\n"
        has_conflict, _ = check_dep_conflict(text)
        assert has_conflict is False

    def test_duplicate_same_version(self) -> None:
        text = "flask>=2.0\nflask>=2.0\n"
        has_conflict, _ = check_dep_conflict(text)
        assert has_conflict is False


# ---------------------------------------------------------------------------
# check_mock_coverage
# ---------------------------------------------------------------------------


class TestCheckMockCoverage:
    """Tests for mock-coverage detection."""

    def test_no_external_calls(self) -> None:
        code = "x = 1\nprint(x)\n"
        coverage, unmocked = check_mock_coverage(code)
        assert coverage == 1.0
        assert unmocked == []

    def test_mocked_requests(self) -> None:
        code = """\
from unittest.mock import patch, MagicMock

with patch("requests.get") as mock_get:
    mock_get.return_value = MagicMock(status_code=200)
    import requests
    resp = requests.get("http://example.com")
"""
        coverage, unmocked = check_mock_coverage(code)
        assert coverage == 1.0

    def test_unmocked_requests(self) -> None:
        code = """\
import requests
resp = requests.get("http://example.com")
print(resp.status_code)
"""
        coverage, unmocked = check_mock_coverage(code)
        assert coverage < 1.0
        assert len(unmocked) > 0

    def test_empty_code(self) -> None:
        coverage, unmocked = check_mock_coverage("")
        assert coverage == 1.0
        assert unmocked == []

    def test_mock_with_side_effect(self) -> None:
        code = """\
from unittest.mock import patch

def test_fetch():
    with patch("requests.get", side_effect=ConnectionError("refused")):
        pass
"""
        coverage, unmocked = check_mock_coverage(code)
        assert coverage == 1.0

    def test_sqlite3_memory_is_ok(self) -> None:
        """:memory: sqlite3 connections are fine — no real DB."""
        code = "import sqlite3\nconn = sqlite3.connect(':memory:')\n"
        coverage, unmocked = check_mock_coverage(code)
        assert coverage == 1.0

    def test_sqlite3_real_file_detected(self) -> None:
        code = "import sqlite3\nconn = sqlite3.connect('real.db')\n"
        coverage, unmocked = check_mock_coverage(code)
        assert coverage < 1.0


# ---------------------------------------------------------------------------
# evaluate_single / evaluate_batch
# ---------------------------------------------------------------------------


class TestEvaluateSingle:
    """Tests for single-generation evaluation."""

    def test_good_generation(self) -> None:
        gen = GenerationInput(
            trace_name="test",
            files={
                "reproduce.py": "raise ValueError('test')\n",
                "requirements.txt": "requests>=2.28\n",
                "mock_data.json": "{}",
            },
            tokens_used=500,
            expected_error="ValueError: test",
        )
        result = evaluate_single(gen)
        assert result.runnable is True
        assert result.dep_conflict is False
        assert result.mock_coverage == 1.0
        assert result.error_reproduced is True
        assert result.tokens_used == 500

    def test_bad_generation(self) -> None:
        gen = GenerationInput(
            trace_name="bad",
            files={
                "reproduce.py": "import nonexistent_module\n",
                "requirements.txt": "foo>=1\nfoo<1\n",
                "mock_data.json": "{}",
            },
            tokens_used=300,
            expected_error="ValueError: x",
        )
        result = evaluate_single(gen)
        assert result.runnable is False
        assert result.dep_conflict is True
        assert result.error_reproduced is False

    def test_no_expected_error(self) -> None:
        """When no expected_error is provided, error_reproduced stays False."""
        gen = GenerationInput(
            trace_name="t",
            files={"reproduce.py": "print('hi')\n"},
            tokens_used=100,
        )
        result = evaluate_single(gen)
        assert result.runnable is True
        assert result.error_reproduced is False


class TestEvaluateBatch:
    """Tests for batch evaluation and reporting."""

    def test_batch_rates(self) -> None:
        inputs = [
            GenerationInput(
                trace_name="good",
                files={
                    "reproduce.py": "raise ValueError('x')\n",
                    "requirements.txt": "requests>=2.0\n",
                    "mock_data.json": "{}",
                },
                tokens_used=400,
                expected_error="ValueError: x",
            ),
            GenerationInput(
                trace_name="bad",
                files={
                    "reproduce.py": "import nonexistent_xyz\n",
                    "requirements.txt": "a>=1\na<1\n",
                    "mock_data.json": "{}",
                },
                tokens_used=600,
                expected_error="TypeError: y",
            ),
        ]
        batch = evaluate_batch(inputs)
        assert batch.total == 2
        assert batch.runnable_rate == 0.5  # only "good" is runnable
        assert batch.dep_conflict_rate == 0.5  # only "bad" has conflict
        assert batch.error_reproduced_rate == 0.5  # only "good" reproduces

    def test_token_efficiency(self) -> None:
        inputs = [
            GenerationInput(
                trace_name="t",
                files={
                    "reproduce.py": "raise ValueError('x')\n",
                    "requirements.txt": "",
                    "mock_data.json": "{}",
                },
                tokens_used=1000,
                expected_error="ValueError: x",
            ),
        ]
        batch = evaluate_batch(inputs)
        # 1 error reproduced / 1000 tokens * 1000 = 1.0
        assert batch.token_efficiency == pytest.approx(1.0)

    def test_empty_batch(self) -> None:
        batch = evaluate_batch([])
        assert batch.total == 0
        assert batch.runnable_rate == 0.0
        assert batch.report() != ""

    def test_report_contains_table(self) -> None:
        inputs = [
            GenerationInput(
                trace_name="t",
                files={"reproduce.py": "x = 1\n", "requirements.txt": "", "mock_data.json": "{}"},
                tokens_used=100,
            ),
        ]
        batch = evaluate_batch(inputs)
        report = batch.report()
        assert "代码可运行率" in report
        assert "依赖冲突率" in report
        assert "Mock 覆盖率" in report
        assert "Token 效率" in report
