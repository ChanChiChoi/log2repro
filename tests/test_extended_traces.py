"""Robustness tests for 20 extended trace fixtures.

Categories:
- Nested calls (decorator, middleware, recursion, contextmanager, callback)
- Dynamic imports (importlib, __import__, lazy, plugin_chain, reload)
- Async errors (TaskGroup, generator, wait_for, semaphore, event_loop)
- C extensions (numpy, ctypes, sqlite3, mmap, signal, pickle, orjson, zlib, struct)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from log2repro.parsers.stacktrace import StacktraceParser

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def parser() -> StacktraceParser:
    return StacktraceParser()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


def _parse(name: str, parser: StacktraceParser):
    return parser.parse(_load(name))


# ---------------------------------------------------------------------------
# Nested call traces
# ---------------------------------------------------------------------------


class TestNestedCalls:
    """Traces with deep/complex call stacks."""

    @pytest.mark.parametrize("fixture,expected_error", [
        ("trace_nested_decorator.log", "SchemaError"),
        ("trace_nested_middleware.log", "KeyError"),
        ("trace_nested_recursion.log", "UndefinedFunction"),
        ("trace_nested_contextmanager.log", "ProgrammingError"),
        ("trace_nested_callback.log", "TemplateError"),
    ])
    def test_parseable(self, parser: StacktraceParser, fixture: str, expected_error: str) -> None:
        traces = _parse(fixture, parser)
        assert len(traces) >= 1
        assert any(expected_error in t.error for t in traces)

    def test_decorator_deep_chain(self, parser: StacktraceParser) -> None:
        """Deep call chain through engine → stages → transforms → validation."""
        traces = _parse("trace_nested_decorator.log", parser)
        t = traces[0]
        assert len(t.chain) >= 5
        assert any("validation.py" in c for c in t.chain)

    def test_middleware_chain(self, parser: StacktraceParser) -> None:
        """Middleware dispatch chain."""
        traces = _parse("trace_nested_middleware.log", parser)
        t = traces[0]
        assert any("auth.py" in c for c in t.chain)

    def test_recursion_with_depth(self, parser: StacktraceParser) -> None:
        """Recursive AST evaluator call stack."""
        traces = _parse("trace_nested_recursion.log", parser)
        t = traces[0]
        eval_entries = [c for c in t.chain if "_eval_node" in c or "_eval_binary_op" in c]
        assert len(eval_entries) >= 3

    def test_contextmanager_error(self, parser: StacktraceParser) -> None:
        """Error inside a context manager."""
        traces = _parse("trace_nested_contextmanager.log", parser)
        t = traces[0]
        assert "closed database" in t.error or "ProgrammingError" in t.error

    def test_callback_chain(self, parser: StacktraceParser) -> None:
        """Event emitter → handler → template rendering."""
        traces = _parse("trace_nested_callback.log", parser)
        t = traces[0]
        assert len(t.chain) >= 3


# ---------------------------------------------------------------------------
# Dynamic import traces
# ---------------------------------------------------------------------------


class TestDynamicImports:
    """Traces involving importlib, __import__, lazy imports, plugin loading."""

    @pytest.mark.parametrize("fixture,expected_error", [
        ("trace_dynamic_importlib.log", "ModuleNotFoundError"),
        ("trace_dynamic_dunder_import.log", "ConfigError"),
        ("trace_dynamic_lazy.log", "TypeError"),
        ("trace_dynamic_plugin_chain.log", "ModuleNotFoundError"),
        ("trace_dynamic_reload.log", "PydanticUserError"),
    ])
    def test_parseable(self, parser: StacktraceParser, fixture: str, expected_error: str) -> None:
        traces = _parse(fixture, parser)
        assert len(traces) >= 1
        assert any(expected_error in t.error for t in traces)

    def test_importlib_has_frozen_frames(self, parser: StacktraceParser) -> None:
        """importlib traces include frozen bootstrap frames."""
        traces = _parse("trace_dynamic_importlib.log", parser)
        t = traces[0]
        chain_text = " ".join(t.chain)
        assert "importlib" in chain_text or "loader" in chain_text

    def test_dunder_import_chained(self, parser: StacktraceParser) -> None:
        """__import__ failure with chained AttributeError → ConfigError."""
        traces = _parse("trace_dynamic_dunder_import.log", parser)
        assert len(traces) >= 1
        # At least one trace should reference registry.py
        all_chain = " ".join(c for t in traces for c in t.chain)
        assert "registry.py" in all_chain

    def test_lazy_import_inline(self, parser: StacktraceParser) -> None:
        """Lazy import inside a function body."""
        traces = _parse("trace_dynamic_lazy.log", parser)
        t = traces[0]
        assert "data_export.py" in t.file

    def test_plugin_chain_multiple_files(self, parser: StacktraceParser) -> None:
        """Plugin loading chain crosses multiple files."""
        traces = _parse("trace_dynamic_plugin_chain.log", parser)
        t = traces[0]
        files = {c.split(":")[0] for c in t.chain}
        assert len(files) >= 2

    def test_reload_triggers_pydantic(self, parser: StacktraceParser) -> None:
        """Module reload triggering Pydantic validation."""
        traces = _parse("trace_dynamic_reload.log", parser)
        t = traces[0]
        assert "PydanticUserError" in t.error or "email-validator" in t.error


# ---------------------------------------------------------------------------
# Async error traces
# ---------------------------------------------------------------------------


class TestAsyncErrors:
    """Traces involving asyncio, TaskGroup, async generators, timeouts."""

    @pytest.mark.parametrize("fixture,expected_error", [
        ("trace_async_taskgroup.log", "ExceptionGroup"),
        ("trace_async_generator.log", "StreamError"),
        ("trace_async_wait_for.log", "TimeoutError"),
        ("trace_async_semaphore.log", "RuntimeError"),
        ("trace_async_event_loop.log", "ClientResponseError"),
    ])
    def test_parseable(self, parser: StacktraceParser, fixture: str, expected_error: str) -> None:
        traces = _parse(fixture, parser)
        assert len(traces) >= 1
        assert any(expected_error in t.error for t in traces)

    def test_taskgroup_exception_group(self, parser: StacktraceParser) -> None:
        """ExceptionGroup with sub-exception."""
        traces = _parse("trace_async_taskgroup.log", parser)
        t = traces[0]
        assert "TaskGroup" in t.error or "ClientConnectorError" in t.error

    def test_generator_yields_in_chain(self, parser: StacktraceParser) -> None:
        """Async generator trace with yield."""
        traces = _parse("trace_async_generator.log", parser)
        t = traces[0]
        assert "reader.py" in t.file or "stream" in t.error.lower()

    def test_timeout_error(self, parser: StacktraceParser) -> None:
        """asyncio.wait_for timeout."""
        traces = _parse("trace_async_wait_for.log", parser)
        t = traces[0]
        assert "TimeoutError" in t.error

    def test_semaphore_shutdown(self, parser: StacktraceParser) -> None:
        """Semaphore acquire during shutdown."""
        traces = _parse("trace_async_semaphore.log", parser)
        assert len(traces) >= 1

    def test_event_loop_missing(self, parser: StacktraceParser) -> None:
        """No event loop in thread + subsequent 404."""
        traces = _parse("trace_async_event_loop.log", parser)
        assert len(traces) >= 1
        errors = [t.error for t in traces]
        assert any("404" in e or "ClientResponseError" in e for e in errors)


# ---------------------------------------------------------------------------
# C extension error traces
# ---------------------------------------------------------------------------


class TestCExtensionErrors:
    """Traces from C-backed modules (numpy, sqlite3, struct, zlib, etc.)."""

    @pytest.mark.parametrize("fixture,expected_error", [
        ("trace_cext_numpy.log", "_UFuncNoLoopError"),
        ("trace_cext_ctypes.log", "NativeError"),
        ("trace_cext_sqlite3.log", "OperationalError"),
        ("trace_cext_mmap.log", "SearchError"),
        ("trace_cext_signal.log", "SupervisorError"),
        ("trace_cext_pickle.log", "CacheError"),
        ("trace_cext_json_cext.log", "APIError"),
        ("trace_cext_zlib.log", "StorageError"),
        ("trace_cext_struct.log", "ConnectionError"),
    ])
    def test_parseable(self, parser: StacktraceParser, fixture: str, expected_error: str) -> None:
        traces = _parse(fixture, parser)
        assert len(traces) >= 1
        assert any(expected_error in t.error for t in traces)

    def test_numpy_dtype_error(self, parser: StacktraceParser) -> None:
        """NumPy dtype mismatch error."""
        traces = _parse("trace_cext_numpy.log", parser)
        t = traces[0]
        assert "numpy" in t.file or "pipeline.py" in t.file

    def test_ctypes_oserror_chained(self, parser: StacktraceParser) -> None:
        """ctypes OSError → NativeError chain."""
        traces = _parse("trace_cext_ctypes.log", parser)
        assert len(traces) >= 1

    def test_sqlite3_locked(self, parser: StacktraceParser) -> None:
        """sqlite3 database locked error."""
        traces = _parse("trace_cext_sqlite3.log", parser)
        t = traces[0]
        assert "locked" in t.error or "OperationalError" in t.error

    def test_mmap_out_of_range(self, parser: StacktraceParser) -> None:
        """mmap offset out of range."""
        traces = _parse("trace_cext_mmap.log", parser)
        assert len(traces) >= 1

    def test_too_many_open_files(self, parser: StacktraceParser) -> None:
        """OSError: too many open files."""
        traces = _parse("trace_cext_signal.log", parser)
        t = traces[0]
        assert "open files" in t.error or "SupervisorError" in t.error

    def test_pickle_corruption(self, parser: StacktraceParser) -> None:
        """Pickle deserialization failure."""
        traces = _parse("trace_cext_pickle.log", parser)
        t = traces[0]
        assert "CacheError" in t.error or "UnpicklingError" in t.error

    def test_orjson_parse_error(self, parser: StacktraceParser) -> None:
        """orjson JSON parse error."""
        traces = _parse("trace_cext_json_cext.log", parser)
        assert len(traces) >= 1

    def test_zlib_triple_chain(self, parser: StacktraceParser) -> None:
        """zlib → StorageError → APIError triple chain."""
        traces = _parse("trace_cext_zlib.log", parser)
        assert len(traces) >= 2

    def test_struct_triple_chain(self, parser: StacktraceParser) -> None:
        """struct → ProtocolError → ConnectionError triple chain."""
        traces = _parse("trace_cext_struct.log", parser)
        assert len(traces) >= 2


# ---------------------------------------------------------------------------
# Cross-category consistency
# ---------------------------------------------------------------------------


class TestCrossCategoryConsistency:
    """Ensure all 20 fixtures are parseable and produce valid output."""

    ALL_FIXTURES = [
        # Nested
        "trace_nested_decorator.log",
        "trace_nested_middleware.log",
        "trace_nested_recursion.log",
        "trace_nested_contextmanager.log",
        "trace_nested_callback.log",
        # Dynamic imports
        "trace_dynamic_importlib.log",
        "trace_dynamic_dunder_import.log",
        "trace_dynamic_lazy.log",
        "trace_dynamic_plugin_chain.log",
        "trace_dynamic_reload.log",
        # Async
        "trace_async_taskgroup.log",
        "trace_async_generator.log",
        "trace_async_wait_for.log",
        "trace_async_semaphore.log",
        "trace_async_event_loop.log",
        # C extensions
        "trace_cext_numpy.log",
        "trace_cext_ctypes.log",
        "trace_cext_sqlite3.log",
        "trace_cext_mmap.log",
        "trace_cext_signal.log",
    ]

    @pytest.fixture(params=ALL_FIXTURES)
    def fixture_name(self, request: pytest.FixtureRequest) -> str:
        return request.param

    def test_returns_list(self, parser: StacktraceParser, fixture_name: str) -> None:
        traces = _parse(fixture_name, parser)
        assert isinstance(traces, list)
        assert len(traces) >= 1

    def test_has_error_string(self, parser: StacktraceParser, fixture_name: str) -> None:
        for t in _parse(fixture_name, parser):
            assert t.error
            assert isinstance(t.error, str)

    def test_has_valid_file(self, parser: StacktraceParser, fixture_name: str) -> None:
        for t in _parse(fixture_name, parser):
            assert t.file

    def test_has_positive_line(self, parser: StacktraceParser, fixture_name: str) -> None:
        for t in _parse(fixture_name, parser):
            assert t.line > 0

    def test_has_chain(self, parser: StacktraceParser, fixture_name: str) -> None:
        for t in _parse(fixture_name, parser):
            assert len(t.chain) >= 1
