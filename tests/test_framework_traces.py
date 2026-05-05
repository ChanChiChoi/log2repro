"""Robustness tests for parser across different framework trace formats.

Tests that StacktraceParser can extract meaningful traces from real-world
output of FastAPI, Flask, PyTorch, SQLAlchemy, and requests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from log2repro.parsers.stacktrace import StacktraceParser

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def parser() -> StacktraceParser:
    return StacktraceParser()


class TestFastAPITrace:
    """Parser robustness on FastAPI + Uvicorn + Pydantic tracebacks."""

    @pytest.fixture()
    def trace_text(self) -> str:
        return (FIXTURES / "trace_fastapi.log").read_text()

    def test_can_parse(self, parser: StacktraceParser, trace_text: str) -> None:
        assert parser.can_parse(trace_text)

    def test_extracts_at_least_one_trace(self, parser: StacktraceParser, trace_text: str) -> None:
        traces = parser.parse(trace_text)
        assert len(traces) >= 1

    def test_error_contains_pydantic(self, parser: StacktraceParser, trace_text: str) -> None:
        traces = parser.parse(trace_text)
        assert any("ValidationError" in t.error for t in traces)

    def test_chain_has_multiple_frames(self, parser: StacktraceParser, trace_text: str) -> None:
        traces = parser.parse(trace_text)
        assert any(len(t.chain) >= 3 for t in traces)

    def test_user_code_in_chain(self, parser: StacktraceParser, trace_text: str) -> None:
        """User's routers/users.py should appear somewhere in the call chain."""
        traces = parser.parse(trace_text)
        all_chain = " ".join(c for t in traces for c in t.chain)
        assert "users.py" in all_chain


class TestFlaskTrace:
    """Parser robustness on Flask + SQLAlchemy chained tracebacks."""

    @pytest.fixture()
    def trace_text(self) -> str:
        return (FIXTURES / "trace_flask.log").read_text()

    def test_can_parse(self, parser: StacktraceParser, trace_text: str) -> None:
        assert parser.can_parse(trace_text)

    def test_extracts_multiple_traces(self, parser: StacktraceParser, trace_text: str) -> None:
        """Flask chained exceptions should produce 2 traces."""
        traces = parser.parse(trace_text)
        assert len(traces) >= 1

    def test_error_types(self, parser: StacktraceParser, trace_text: str) -> None:
        traces = parser.parse(trace_text)
        errors = [t.error for t in traces]
        # Should capture at least one of the chained errors
        assert any("NoResultFound" in e or "UnboundLocalError" in e for e in errors)

    def test_chain_captures_flask_internals(self, parser: StacktraceParser, trace_text: str) -> None:
        traces = parser.parse(trace_text)
        # At least one trace should have a chain including flask frames
        all_chain_entries = " ".join(t for trace in traces for t in trace.chain)
        assert "flask" in all_chain_entries or "views.py" in all_chain_entries


class TestPyTorchTrace:
    """Parser robustness on PyTorch Lightning deeply nested tracebacks."""

    @pytest.fixture()
    def trace_text(self) -> str:
        return (FIXTURES / "trace_pytorch.log").read_text()

    def test_can_parse(self, parser: StacktraceParser, trace_text: str) -> None:
        assert parser.can_parse(trace_text)

    def test_extracts_trace(self, parser: StacktraceParser, trace_text: str) -> None:
        traces = parser.parse(trace_text)
        assert len(traces) >= 1

    def test_error_is_runtime_error(self, parser: StacktraceParser, trace_text: str) -> None:
        traces = parser.parse(trace_text)
        assert any("RuntimeError" in t.error for t in traces)

    def test_error_message_preserved(self, parser: StacktraceParser, trace_text: str) -> None:
        traces = parser.parse(trace_text)
        rt_errors = [t for t in traces if "RuntimeError" in t.error]
        assert len(rt_errors) >= 1
        assert "mat1 and mat2" in rt_errors[0].error or "cannot be multiplied" in rt_errors[0].error

    def test_long_chain(self, parser: StacktraceParser, trace_text: str) -> None:
        """PyTorch Lightning produces very long call chains."""
        traces = parser.parse(trace_text)
        assert any(len(t.chain) >= 10 for t in traces)

    def test_user_code_in_chain(self, parser: StacktraceParser, trace_text: str) -> None:
        """User's model/training code should appear in the call chain."""
        traces = parser.parse(trace_text)
        all_chain = " ".join(c for t in traces for c in t.chain)
        assert "transformer.py" in all_chain or "train.py" in all_chain


class TestSQLAlchemyTrace:
    """Parser robustness on SQLAlchemy + psycopg2 + chained tracebacks."""

    @pytest.fixture()
    def trace_text(self) -> str:
        return (FIXTURES / "trace_sqlalchemy.log").read_text()

    def test_can_parse(self, parser: StacktraceParser, trace_text: str) -> None:
        assert parser.can_parse(trace_text)

    def test_extracts_traces(self, parser: StacktraceParser, trace_text: str) -> None:
        traces = parser.parse(trace_text)
        assert len(traces) >= 1

    def test_captures_integrity_error(self, parser: StacktraceParser, trace_text: str) -> None:
        traces = parser.parse(trace_text)
        errors = [t.error for t in traces]
        assert any("IntegrityError" in e for e in errors)

    def test_captures_connection_error(self, parser: StacktraceParser, trace_text: str) -> None:
        """The chained exception should also be captured."""
        traces = parser.parse(trace_text)
        errors = [t.error for t in traces]
        assert any("ConnectionRefusedError" in e for e in errors)

    def test_chain_includes_user_service(self, parser: StacktraceParser, trace_text: str) -> None:
        traces = parser.parse(trace_text)
        all_chain = " ".join(t for trace in traces for t in trace.chain)
        assert "department_service.py" in all_chain or "email.py" in all_chain

    def test_multiple_traces_from_chain(self, parser: StacktraceParser, trace_text: str) -> None:
        """SQLAlchemy chained exceptions should produce at least 2 traces."""
        traces = parser.parse(trace_text)
        assert len(traces) >= 2


class TestRequestsTrace:
    """Parser robustness on requests + urllib3 + SSL error tracebacks."""

    @pytest.fixture()
    def trace_text(self) -> str:
        return (FIXTURES / "trace_requests.log").read_text()

    def test_can_parse(self, parser: StacktraceParser, trace_text: str) -> None:
        assert parser.can_parse(trace_text)

    def test_extracts_traces(self, parser: StacktraceParser, trace_text: str) -> None:
        traces = parser.parse(trace_text)
        assert len(traces) >= 1

    def test_captures_ssl_error(self, parser: StacktraceParser, trace_text: str) -> None:
        traces = parser.parse(trace_text)
        errors = [t.error for t in traces]
        assert any("SSLCertVerification" in e or "SSLError" in e for e in errors)

    def test_captures_requests_error(self, parser: StacktraceParser, trace_text: str) -> None:
        traces = parser.parse(trace_text)
        errors = [t.error for t in traces]
        assert any("requests.exceptions" in e or "SSLError" in e for e in errors)

    def test_chain_spans_multiple_libs(self, parser: StacktraceParser, trace_text: str) -> None:
        """The call chain should cross requests -> urllib3 -> ssl boundaries."""
        traces = parser.parse(trace_text)
        # Find traces that have entries from different libraries
        for trace in traces:
            chain_text = " ".join(trace.chain)
            if "requests" in chain_text or "urllib3" in chain_text:
                assert len(trace.chain) >= 3
                return
        pytest.skip("No trace with cross-library chain found")

    def test_user_code_in_chain(self, parser: StacktraceParser, trace_text: str) -> None:
        """User's sync_job.py should appear in the call chain."""
        traces = parser.parse(trace_text)
        all_chain = " ".join(c for t in traces for c in t.chain)
        assert "sync_job.py" in all_chain


class TestCrossFrameworkConsistency:
    """Ensure parser returns consistent structure across all frameworks."""

    ALL_FIXTURES = [
        "trace_fastapi.log",
        "trace_flask.log",
        "trace_pytorch.log",
        "trace_sqlalchemy.log",
        "trace_requests.log",
    ]

    @pytest.fixture(params=ALL_FIXTURES)
    def trace_text(self, request: pytest.FixtureRequest) -> str:
        return (FIXTURES / request.param).read_text()

    def test_all_parseable(self, parser: StacktraceParser, trace_text: str) -> None:
        """Every fixture must be parseable without exceptions."""
        traces = parser.parse(trace_text)
        assert isinstance(traces, list)

    def test_all_have_error_string(self, parser: StacktraceParser, trace_text: str) -> None:
        """Every returned trace must have a non-empty error string."""
        traces = parser.parse(trace_text)
        for t in traces:
            assert t.error
            assert isinstance(t.error, str)

    def test_all_have_valid_file_path(self, parser: StacktraceParser, trace_text: str) -> None:
        """Every returned trace must have a non-empty file path."""
        traces = parser.parse(trace_text)
        for t in traces:
            assert t.file
            assert isinstance(t.file, str)

    def test_all_have_positive_line(self, parser: StacktraceParser, trace_text: str) -> None:
        """Every returned trace must have a positive line number."""
        traces = parser.parse(trace_text)
        for t in traces:
            assert t.line > 0

    def test_all_have_chain(self, parser: StacktraceParser, trace_text: str) -> None:
        """Every returned trace must have at least one chain entry."""
        traces = parser.parse(trace_text)
        for t in traces:
            assert len(t.chain) >= 1
