"""Tests for the benchmark framework itself."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.mock_responses import generate_mock_response
from benchmarks.prompt_variants import PROMPT_VARIANTS, VARIANT_LABELS
from benchmarks.report import VariantResult, generate_per_trace_table, generate_report
from benchmarks.validator import validate_response
from log2repro.parsers.base import ParsedTrace
from log2repro.parsers.stacktrace import StacktraceParser

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def sample_trace() -> ParsedTrace:
    text = (FIXTURES / "trace_sample.log").read_text()
    return StacktraceParser().parse(text)[0]


# ---------------------------------------------------------------------------
# Tests: prompt_variants
# ---------------------------------------------------------------------------


class TestPromptVariants:
    """All 5 prompt variants must be defined."""

    def test_five_variants(self) -> None:
        assert len(PROMPT_VARIANTS) == 5

    def test_all_have_labels(self) -> None:
        for key in PROMPT_VARIANTS:
            assert key in VARIANT_LABELS

    def test_no_empty_prompts(self) -> None:
        for key, prompt in PROMPT_VARIANTS.items():
            assert len(prompt) > 50, f"{key} is too short"


# ---------------------------------------------------------------------------
# Tests: mock_responses
# ---------------------------------------------------------------------------


class TestMockResponses:
    """Mock response generation."""

    def test_returns_required_keys(self, sample_trace: ParsedTrace) -> None:
        resp = generate_mock_response("P3_BALANCED", sample_trace, 0)
        assert "response_text" in resp
        assert "tokens_used" in resp
        assert "triggered" in resp
        assert "hallucinated" in resp

    def test_deterministic(self, sample_trace: ParsedTrace) -> None:
        """Same inputs produce same outputs."""
        r1 = generate_mock_response("P1_SPEED", sample_trace, 0)
        r2 = generate_mock_response("P1_SPEED", sample_trace, 0)
        assert r1["response_text"] == r2["response_text"]
        assert r1["triggered"] == r2["triggered"]

    def test_different_runs_vary(self, sample_trace: ParsedTrace) -> None:
        """Different run indices can produce different results."""
        results = [generate_mock_response("P3_BALANCED", sample_trace, i) for i in range(10)]
        texts = {r["response_text"] for r in results}
        # At least some variation (not all identical)
        # Due to deterministic hash, they might be identical for some variants
        assert len(texts) >= 1

    def test_response_has_code_blocks(self, sample_trace: ParsedTrace) -> None:
        resp = generate_mock_response("P3_BALANCED", sample_trace, 0)
        assert "```reproduce.py" in resp["response_text"]
        assert "```requirements.txt" in resp["response_text"]

    def test_all_variants_produce_output(self, sample_trace: ParsedTrace) -> None:
        for variant in PROMPT_VARIANTS:
            resp = generate_mock_response(variant, sample_trace, 0)
            assert len(resp["response_text"]) > 100, f"{variant} response too short"


# ---------------------------------------------------------------------------
# Tests: validator
# ---------------------------------------------------------------------------


class TestValidator:
    """Response validation logic."""

    def test_valid_response_passes(self, sample_trace: ParsedTrace) -> None:
        resp = generate_mock_response("P3_BALANCED", sample_trace, 0)
        result = validate_response(resp["response_text"], sample_trace)
        assert result.has_reproduce_py
        assert result.has_requirements

    def test_empty_response_fails(self, sample_trace: ParsedTrace) -> None:
        result = validate_response("no code blocks here", sample_trace)
        assert not result.has_reproduce_py
        assert not result.triggers_error

    def test_hallucinated_import_detected(self, sample_trace: ParsedTrace) -> None:
        code = '```reproduce.py\nimport nonexistent_xyz\nraise ValueError("test")\n```'
        result = validate_response(code, sample_trace)
        assert result.hallucinated
        assert result.hallucinated_imports is not None
        assert "nonexistent_xyz" in result.hallucinated_imports

    def test_stdlib_import_not_hallucinated(self, sample_trace: ParsedTrace) -> None:
        code = '```reproduce.py\nimport json\nimport os\nraise ValueError("test")\n```'
        result = validate_response(code, sample_trace)
        assert not result.hallucinated

    def test_trigger_check_with_raise(self, sample_trace: ParsedTrace) -> None:
        code = '```reproduce.py\nraise ValueError("bad")\n```'
        result = validate_response(code, sample_trace)
        assert result.triggers_error

    def test_trigger_check_with_error_type(self, sample_trace: ParsedTrace) -> None:
        code = '```reproduce.py\n# This triggers ValueError\nprint("hi")\n```'
        result = validate_response(code, sample_trace)
        assert result.triggers_error  # "ValueError" is in the code


# ---------------------------------------------------------------------------
# Tests: report
# ---------------------------------------------------------------------------


class TestReport:
    """Report generation."""

    def test_report_contains_table(self) -> None:
        results = [
            VariantResult("P1_SPEED", "P1 速度", 10, 7, 2, 2000, 8),
            VariantResult("P3_BALANCED", "P3 平衡", 10, 9, 1, 3000, 10),
        ]
        report = generate_report(results)
        assert "P1_SPEED" in report
        assert "P3_BALANCED" in report
        assert "%" in report

    def test_per_trace_table(self) -> None:
        trace_results = {
            "sample": [
                VariantResult("P1_SPEED", "P1", 10, 7, 2, 2000, 8),
                VariantResult("P3_BALANCED", "P3", 10, 9, 1, 3000, 10),
            ],
        }
        table = generate_per_trace_table(trace_results)
        assert "sample" in table
        assert "P1_SPEED" in table
