"""Tests for the parsers module."""

from __future__ import annotations

import pytest

from log2repro.parsers.base import BaseParser, ParsedTrace
from log2repro.parsers.stacktrace import StacktraceParser


# ---------------------------------------------------------------------------
# ParsedTrace model tests
# ---------------------------------------------------------------------------


class TestParsedTrace:
    """Tests for the ParsedTrace Pydantic model."""

    def test_minimal_creation(self) -> None:
        """A ParsedTrace can be created with only required fields."""
        trace = ParsedTrace(file="app.py", line=10, error="ValueError: bad")
        assert trace.file == "app.py"
        assert trace.line == 10
        assert trace.error == "ValueError: bad"
        assert trace.context_vars == []
        assert trace.chain == []

    def test_full_creation(self) -> None:
        """All fields are accepted."""
        trace = ParsedTrace(
            file="app.py",
            line=42,
            error="KeyError: 'x'",
            context_vars=["data", "key"],
            chain=["app.py:main:10", "app.py:run:42"],
        )
        assert len(trace.context_vars) == 2
        assert len(trace.chain) == 2

    def test_to_context_dict(self) -> None:
        """to_context_dict returns a plain dict with all fields."""
        trace = ParsedTrace(file="a.py", line=1, error="E")
        d = trace.to_context_dict()
        assert isinstance(d, dict)
        assert d["file"] == "a.py"
        assert d["line"] == 1

    def test_invalid_line_number(self) -> None:
        """Negative line numbers are rejected by Pydantic validation."""
        with pytest.raises(Exception):
            ParsedTrace(file="a.py", line=-1, error="E")


# ---------------------------------------------------------------------------
# BaseParser tests
# ---------------------------------------------------------------------------


class TestBaseParser:
    """Tests for the BaseParser abstract base class."""

    def test_cannot_instantiate(self) -> None:
        """BaseParser is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            BaseParser()  # type: ignore[abstract]

    def test_subclass_must_implement_parse(self) -> None:
        """A subclass without parse() cannot be instantiated."""

        class Incomplete(BaseParser):
            pass

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# StacktraceParser tests
# ---------------------------------------------------------------------------


class TestStacktraceParser:
    """Tests for the StacktraceParser."""

    @pytest.fixture()
    def parser(self) -> StacktraceParser:
        return StacktraceParser()

    def test_can_parse_valid_traceback(self, parser: StacktraceParser) -> None:
        """can_parse returns True for a valid Python traceback."""
        text = 'Traceback (most recent call last):\n  File "x.py", line 1\nError'
        assert parser.can_parse(text) is True

    def test_can_parse_empty(self, parser: StacktraceParser) -> None:
        """can_parse returns False for empty input."""
        assert parser.can_parse("") is False

    def test_can_parse_plain_text(self, parser: StacktraceParser) -> None:
        """can_parse returns False for text without traceback header."""
        assert parser.can_parse("just some random text") is False

    def test_parse_single_trace(self, parser: StacktraceParser) -> None:
        """A single traceback produces one ParsedTrace."""
        text = (
            'Traceback (most recent call last):\n'
            '  File "app.py", line 10, in main\n'
            '    result = process_data(data)\n'
            'ValueError: invalid data'
        )
        traces = parser.parse(text)
        assert len(traces) == 1
        t = traces[0]
        assert t.file == "app.py"
        assert t.line == 10
        assert t.error == "ValueError: invalid data"
        assert len(t.chain) == 1

    def test_parse_multi_frame_trace(self, parser: StacktraceParser) -> None:
        """A multi-frame traceback captures the full call chain."""
        text = (
            'Traceback (most recent call last):\n'
            '  File "app.py", line 10, in main\n'
            '    result = process_data(data)\n'
            '  File "app.py", line 25, in process_data\n'
            '    validated = validate_input(payload)\n'
            '  File "utils.py", line 42, in validate_input\n'
            '    if user_id is None:\n'
            'ValueError: user_id must not be None'
        )
        traces = parser.parse(text)
        assert len(traces) == 1
        t = traces[0]
        assert t.file == "utils.py"
        assert t.line == 42
        assert t.error == "ValueError: user_id must not be None"
        assert len(t.chain) == 3
        assert t.chain[0] == "app.py:main:10"
        assert t.chain[1] == "app.py:process_data:25"
        assert t.chain[2] == "utils.py:validate_input:42"

    def test_parse_extracts_context_vars(self, parser: StacktraceParser) -> None:
        """Variable names are extracted from source lines in the traceback."""
        text = (
            'Traceback (most recent call last):\n'
            '  File "app.py", line 5, in run\n'
            '    result = compute_value(input_data)\n'
            'TypeError: unsupported operand'
        )
        traces = parser.parse(text)
        assert len(traces) == 1
        # "result", "compute_value", "input_data" should be found
        # (single-char names and stopwords are filtered out)
        vars = traces[0].context_vars
        assert "result" in vars
        assert "input_data" in vars

    def test_parse_fixture_file(self, parser: StacktraceParser) -> None:
        """Parsing the fixture file produces correct results."""
        from pathlib import Path

        fixture = Path(__file__).parent / "fixtures" / "trace_sample.log"
        text = fixture.read_text()
        traces = parser.parse(text)
        assert len(traces) == 1
        t = traces[0]
        assert t.file == "/home/user/project/utils.py"
        assert t.line == 42
        assert "ValueError" in t.error
        assert len(t.chain) == 3

    def test_parse_no_call_sites(self, parser: StacktraceParser) -> None:
        """A traceback header with no call sites returns empty list."""
        text = "Traceback (most recent call last):\nRuntimeError: something"
        traces = parser.parse(text)
        assert traces == []

    def test_parse_chained_exception(self, parser: StacktraceParser) -> None:
        """Chained exceptions produce multiple traces."""
        text = (
            'Traceback (most recent call last):\n'
            '  File "a.py", line 1, in foo\n'
            '    1 / 0\n'
            'ZeroDivisionError: division by zero\n'
            '\n'
            'During handling of the above exception, another exception occurred:\n'
            '\n'
            'Traceback (most recent call last):\n'
            '  File "b.py", line 2, in bar\n'
            '    raise RuntimeError("wrapped")\n'
            'RuntimeError: wrapped'
        )
        traces = parser.parse(text)
        assert len(traces) == 2
        assert "ZeroDivisionError" in traces[0].error
        assert "RuntimeError" in traces[1].error

    def test_error_without_message(self, parser: StacktraceParser) -> None:
        """An exception type without a message is handled gracefully."""
        text = (
            'Traceback (most recent call last):\n'
            '  File "x.py", line 1, in f\n'
            '    pass\n'
            'KeyboardInterrupt'
        )
        traces = parser.parse(text)
        assert len(traces) == 1
        assert traces[0].error == "KeyboardInterrupt"
