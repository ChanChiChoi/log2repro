"""Tests for the root cause analysis module (D8).

All tests mock litellm so no real LLM calls are made.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from log2repro.extractors.ast_parser import ASTContext
from log2repro.generators.analysis import (
    _parse_analysis_response,
    generate_analysis,
    generate_analysis_markdown,
)
from log2repro.generators.code_gen import ReproContext
from log2repro.models import AnalysisResult, FixRecommendation
from log2repro.parsers.base import ParsedTrace

FIXTURES = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# Sample LLM analysis responses
# ---------------------------------------------------------------------------

GOOD_ANALYSIS_RESPONSE = """\
## Root Cause

The function `validate()` receives a `None` value for `user_id` because the
upstream API returns an empty body on 404 responses.  The code assumes the
response always contains a `user_id` key but does not guard against `None`.

## Error Type

TypeError — NoneType attribute access

## Affected Code Path

1. `main()` calls `process_data(payload)` at line 10
2. `process_data()` calls `data.get("user_id")` at line 42
3. `validate()` attempts to use `None` as a dict

The fix should be applied in `process_data()` at line 42.

## Impact

- The entire request fails with an unhandled exception
- User sees a 500 Internal Server Error
- No data corruption (the error occurs before any writes)

## Fix Recommendations

[HIGH] Add a None check before accessing user_id.
```python
if data.get("user_id") is None:
    raise ValueError("user_id must not be None")
```

[MEDIUM] Use a default value or raise a descriptive error early.

[LOW] Add retry logic for transient API failures that return empty bodies.
"""

MINIMAL_ANALYSIS_RESPONSE = """\
## Root Cause

Division by zero.

## Error Type

ZeroDivisionError

## Affected Code Path

`calc()` at line 5

## Impact

Program crashes.

## Fix Recommendations

[HIGH] Check divisor before division.
"""

EMPTY_ANALYSIS_RESPONSE = "I cannot analyze this error."

MALFORMED_ANALYSIS_RESPONSE = """\
Some random text without proper sections.

## Root Cause

Maybe a problem somewhere.

## Fix Recommendations

[UNKNOWN] This has an invalid confidence level.
[HIGH] This one is valid.
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_trace() -> ParsedTrace:
    return ParsedTrace(
        file="/app/utils.py",
        line=42,
        error="ValueError: user_id must not be None",
        context_vars=["user_id", "data", "payload"],
        chain=["/app/main.py:main:10", "/app/utils.py:validate:42"],
    )


@pytest.fixture()
def sample_ast_context() -> ASTContext:
    return ASTContext(
        signature="def validate(payload: dict, strict: bool = True) -> dict",
        imports=["import json", "from typing import Optional"],
        known_vars={"user_id": "Optional[int]", "name": "str"},
    )


@pytest.fixture()
def sample_context(
    sample_trace: ParsedTrace,
    sample_ast_context: ASTContext,
) -> ReproContext:
    return ReproContext(
        trace=sample_trace,
        ast_context=sample_ast_context,
        model="gpt-4o",
    )


# ---------------------------------------------------------------------------
# Tests: _parse_analysis_response
# ---------------------------------------------------------------------------


class TestParseAnalysisResponse:
    """Tests for Markdown analysis response parsing."""

    def test_parses_all_sections(self) -> None:
        result = _parse_analysis_response(GOOD_ANALYSIS_RESPONSE)
        assert "None" in result.root_cause
        assert "TypeError" in result.error_type
        assert "process_data" in result.affected_code_path
        assert "500" in result.impact

    def test_parses_recommendations(self) -> None:
        result = _parse_analysis_response(GOOD_ANALYSIS_RESPONSE)
        assert len(result.recommendations) == 3

    def test_recommendation_confidence_levels(self) -> None:
        result = _parse_analysis_response(GOOD_ANALYSIS_RESPONSE)
        confidences = [r.confidence for r in result.recommendations]
        assert "high" in confidences
        assert "medium" in confidences
        assert "low" in confidences

    def test_recommendation_code_snippet(self) -> None:
        result = _parse_analysis_response(GOOD_ANALYSIS_RESPONSE)
        high_rec = [r for r in result.recommendations if r.confidence == "high"][0]
        assert "if data.get" in high_rec.code_snippet

    def test_recommendations_sorted_by_confidence(self) -> None:
        result = _parse_analysis_response(GOOD_ANALYSIS_RESPONSE)
        order = [r.confidence for r in result.recommendations]
        assert order == ["high", "medium", "low"]

    def test_raw_markdown_preserved(self) -> None:
        result = _parse_analysis_response(GOOD_ANALYSIS_RESPONSE)
        assert result.raw_markdown == GOOD_ANALYSIS_RESPONSE

    def test_minimal_response(self) -> None:
        result = _parse_analysis_response(MINIMAL_ANALYSIS_RESPONSE)
        assert "Division by zero" in result.root_cause
        assert len(result.recommendations) == 1
        assert result.recommendations[0].confidence == "high"

    def test_empty_response(self) -> None:
        result = _parse_analysis_response(EMPTY_ANALYSIS_RESPONSE)
        assert result.root_cause == ""
        assert result.recommendations == []

    def test_malformed_response_ignores_unknown_confidence(self) -> None:
        result = _parse_analysis_response(MALFORMED_ANALYSIS_RESPONSE)
        # Only [HIGH] should be parsed, [UNKNOWN] is ignored
        assert len(result.recommendations) == 1
        assert result.recommendations[0].confidence == "high"

    def test_section_without_content(self) -> None:
        text = "## Root Cause\n\n## Error Type\n\nSome type"
        result = _parse_analysis_response(text)
        assert result.root_cause == ""
        assert result.error_type == "Some type"


# ---------------------------------------------------------------------------
# Tests: generate_analysis_markdown
# ---------------------------------------------------------------------------


class TestGenerateAnalysisMarkdown:
    """Tests for analysis.md generation."""

    def test_contains_error_info(self, sample_trace: ParsedTrace) -> None:
        result = AnalysisResult(root_cause="test cause")
        md = generate_analysis_markdown(result, sample_trace)
        assert "ValueError" in md
        assert "/app/utils.py" in md
        assert "42" in md

    def test_contains_root_cause(self, sample_trace: ParsedTrace) -> None:
        result = AnalysisResult(root_cause="The API returns None")
        md = generate_analysis_markdown(result, sample_trace)
        assert "The API returns None" in md

    def test_contains_recommendations_table(self, sample_trace: ParsedTrace) -> None:
        result = AnalysisResult(
            recommendations=[
                FixRecommendation(description="Add None check", confidence="high"),
                FixRecommendation(description="Add retry", confidence="low"),
            ]
        )
        md = generate_analysis_markdown(result, sample_trace)
        assert "| 1 |" in md
        assert "| 2 |" in md
        assert "HIGH" in md
        assert "Add None check" in md

    def test_contains_code_snippets(self, sample_trace: ParsedTrace) -> None:
        result = AnalysisResult(
            recommendations=[
                FixRecommendation(
                    description="Add check",
                    confidence="high",
                    code_snippet="if x is None: raise",
                ),
            ]
        )
        md = generate_analysis_markdown(result, sample_trace)
        assert "```python" in md
        assert "if x is None: raise" in md

    def test_no_recommendations_section(self, sample_trace: ParsedTrace) -> None:
        result = AnalysisResult(root_cause="unknown")
        md = generate_analysis_markdown(result, sample_trace)
        assert "Fix Recommendations" not in md

    def test_placeholder_when_empty(self, sample_trace: ParsedTrace) -> None:
        result = AnalysisResult()
        md = generate_analysis_markdown(result, sample_trace)
        assert "*(not determined)*" in md

    def test_contains_timestamp(self, sample_trace: ParsedTrace) -> None:
        result = AnalysisResult()
        md = generate_analysis_markdown(result, sample_trace)
        assert "Generated by log2repro" in md


# ---------------------------------------------------------------------------
# Tests: generate_analysis (mocked LLM)
# ---------------------------------------------------------------------------


class TestGenerateAnalysis:
    """Tests for the analysis generation pipeline with mocked LLM."""

    MOCK_PATH = "log2repro.generators.analysis._call_llm"

    def test_success(self, sample_context: ReproContext) -> None:
        with patch(self.MOCK_PATH, return_value=GOOD_ANALYSIS_RESPONSE):
            result = generate_analysis(sample_context)

        assert isinstance(result, AnalysisResult)
        assert "None" in result.root_cause
        assert len(result.recommendations) == 3

    def test_calls_with_correct_args(self, sample_context: ReproContext) -> None:
        with patch(self.MOCK_PATH, return_value=GOOD_ANALYSIS_RESPONSE) as mock_call:
            generate_analysis(sample_context, temperature=0.5, max_tokens=1000)

        call_kwargs = mock_call.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o"
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_tokens"] == 1000
        msgs = call_kwargs["messages"]
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"

    def test_system_prompt_is_analysis(self, sample_context: ReproContext) -> None:
        with patch(self.MOCK_PATH, return_value=GOOD_ANALYSIS_RESPONSE) as mock_call:
            generate_analysis(sample_context)

        system_content = mock_call.call_args.kwargs["messages"][0]["content"]
        assert "Root Cause" in system_content
        assert "Fix Recommendations" in system_content

    def test_user_message_contains_ast_context(self, sample_context: ReproContext) -> None:
        with patch(self.MOCK_PATH, return_value=GOOD_ANALYSIS_RESPONSE) as mock_call:
            generate_analysis(sample_context)

        user_msg = mock_call.call_args.kwargs["messages"][1]["content"]
        assert "validate" in user_msg
        assert "import json" in user_msg
        assert "user_id" in user_msg

    def test_extra_body_passed_through(self, sample_context: ReproContext) -> None:
        with patch(self.MOCK_PATH, return_value=GOOD_ANALYSIS_RESPONSE) as mock_call:
            generate_analysis(sample_context, extra_body={"enable_thinking": False})

        call_kwargs = mock_call.call_args.kwargs
        assert call_kwargs["extra_body"] == {"enable_thinking": False}

    def test_raises_on_llm_failure(self, sample_context: ReproContext) -> None:
        with patch(self.MOCK_PATH, side_effect=RuntimeError("API error")):
            with pytest.raises(RuntimeError, match="API error"):
                generate_analysis(sample_context)

    def test_handles_empty_response(self, sample_context: ReproContext) -> None:
        with patch(self.MOCK_PATH, return_value=EMPTY_ANALYSIS_RESPONSE):
            result = generate_analysis(sample_context)

        assert result.root_cause == ""
        assert result.recommendations == []


# ---------------------------------------------------------------------------
# Tests: Python API analyze()
# ---------------------------------------------------------------------------


class TestAnalyzeAPI:
    """Tests for the Python API analyze() function."""

    def test_analyze_function_exists(self) -> None:
        from log2repro import analyze
        assert callable(analyze)

    def test_analyze_with_mock_llm(self) -> None:
        text = (
            'Traceback (most recent call last):\n'
            '  File "x.py", line 1, in f\n'
            '    pass\n'
            'ValueError: test'
        )
        with patch("log2repro.generators.analysis._call_llm", return_value=GOOD_ANALYSIS_RESPONSE):
            from log2repro import analyze
            result = analyze(text, model="gpt-4o")

        assert isinstance(result, AnalysisResult)
        assert "None" in result.root_cause

    def test_analyze_empty_input_raises(self) -> None:
        from log2repro import analyze
        with pytest.raises(ValueError, match="Could not extract"):
            analyze("random text without traceback")

    def test_analyze_exports(self) -> None:
        from log2repro import AnalysisResult, FixRecommendation, analyze
        assert callable(analyze)
        assert hasattr(AnalysisResult, "root_cause")
        assert hasattr(FixRecommendation, "confidence")


# ---------------------------------------------------------------------------
# Tests: CLI --analyze flag
# ---------------------------------------------------------------------------


class TestCLIAnalyze:
    """Tests for the --analyze CLI flag."""

    from typer.testing import CliRunner

    runner = CliRunner()

    def _get_app(self):
        from log2repro.cli import app
        return app

    def test_analyze_flag_exists(self) -> None:
        app = self._get_app()
        result = self.runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--analyze" in result.output

    def test_analyze_produces_analysis_md(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "output"
        text = (
            'Traceback (most recent call last):\n'
            '  File "x.py", line 1, in f\n'
            '    pass\n'
            'ValueError: test'
        )
        with (
            patch("log2repro.generators.code_gen._call_llm", return_value=GOOD_LLM_RESPONSE),
            patch("log2repro.generators.analysis._call_llm", return_value=GOOD_ANALYSIS_RESPONSE),
            patch("log2repro.validators.sandbox.run_in_sandbox") as mock_sandbox,
        ):
            from log2repro.validators.sandbox import SandboxResult
            mock_sandbox.return_value = SandboxResult(error_reproduced=True)
            app = self._get_app()
            result = self.runner.invoke(
                app, ["run", text, "--analyze", "--output-dir", str(out_dir)]
            )

        assert result.exit_code == 0
        assert (out_dir / "analysis.md").exists()
        assert (out_dir / "reproduce.py").exists()

    def test_analyze_without_repro(self, tmp_path: Path) -> None:
        """--analyze with --dry-run should still parse (no LLM call)."""
        text = (
            'Traceback (most recent call last):\n'
            '  File "x.py", line 1, in f\n'
            '    pass\n'
            'ValueError: test'
        )
        app = self._get_app()
        result = self.runner.invoke(app, ["run", text, "--dry-run"])
        assert result.exit_code == 0


# Good LLM response for full-pipeline tests (reused from test_cli.py)
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
