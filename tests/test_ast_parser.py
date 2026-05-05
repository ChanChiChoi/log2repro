"""Tests for the AST context extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from log2repro.extractors.ast_parser import (
    ASTContext,
    extract_ast_context,
    extract_ast_context_from_source,
)

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_SOURCE = FIXTURES / "sample_source.py"


# ---------------------------------------------------------------------------
# ASTContext model tests
# ---------------------------------------------------------------------------


class TestASTContext:
    """Tests for the ASTContext Pydantic model."""

    def test_default_creation(self) -> None:
        """Default values are empty containers."""
        ctx = ASTContext()
        assert ctx.signature == ""
        assert ctx.imports == []
        assert ctx.known_vars == {}

    def test_to_context_dict(self) -> None:
        """to_context_dict returns a plain dict."""
        ctx = ASTContext(signature="def foo() -> int", imports=["import os"])
        d = ctx.to_context_dict()
        assert d["signature"] == "def foo() -> int"
        assert d["imports"] == ["import os"]


# ---------------------------------------------------------------------------
# extract_ast_context_from_source tests
# ---------------------------------------------------------------------------


class TestExtractFromSource:
    """Tests for extract_ast_context_from_source (no filesystem)."""

    def test_simple_function(self) -> None:
        """Extracts signature and imports from a simple script."""
        source = (
            "import os\n"
            "from pathlib import Path\n"
            "\n"
            "def greet(name: str) -> str:\n"
            "    return f'Hello {name}'\n"
        )
        ctx = extract_ast_context_from_source(source, target_func="greet")
        assert "def greet(name: str) -> str" in ctx.signature
        assert "import os" in ctx.imports
        assert "from pathlib import Path" in ctx.imports

    def test_global_vars(self) -> None:
        """Annotated global variables are extracted."""
        source = (
            "MAX_RETRIES: int = 3\n"
            "DEBUG: bool = True\n"
        )
        ctx = extract_ast_context_from_source(source)
        assert ctx.known_vars.get("MAX_RETRIES") == "int"
        assert ctx.known_vars.get("DEBUG") == "bool"

    def test_local_vars(self) -> None:
        """Annotated local variables inside the target function are extracted."""
        source = (
            "def process(data: dict) -> dict:\n"
            "    result: dict = {}\n"
            "    count: int = 0\n"
            "    return result\n"
        )
        ctx = extract_ast_context_from_source(source, target_func="process")
        assert ctx.known_vars.get("result") == "dict"
        assert ctx.known_vars.get("count") == "int"

    def test_target_line_lookup(self) -> None:
        """Functions are found by line number when name is not given."""
        source = (
            "def foo():\n"
            "    pass\n"
            "\n"
            "def bar(x: int) -> None:\n"
            "    y: int = x + 1\n"
            "    print(y)\n"
        )
        # Line 5 is inside bar()
        ctx = extract_ast_context_from_source(source, target_line=5)
        assert "def bar(x: int) -> None" in ctx.signature

    def test_async_function(self) -> None:
        """Async function signatures are captured."""
        source = (
            "async def fetch(url: str, timeout: float = 30.0) -> bytes:\n"
            "    data: bytes = b''\n"
            "    return data\n"
        )
        ctx = extract_ast_context_from_source(source, target_func="fetch")
        assert "async def fetch" in ctx.signature
        assert "url: str" in ctx.signature
        assert ctx.known_vars.get("data") == "bytes"

    def test_syntax_error_raises(self) -> None:
        """Invalid Python raises SyntaxError."""
        with pytest.raises(SyntaxError):
            extract_ast_context_from_source("def foo(:\n")

    def test_no_matching_function(self) -> None:
        """Returns empty signature when no function matches."""
        source = "x = 1\n"
        ctx = extract_ast_context_from_source(source, target_func="nope")
        assert ctx.signature == ""

    def test_method_signature(self) -> None:
        """Method signatures include self parameter."""
        source = (
            "class Foo:\n"
            "    def bar(self, x: int, y: str = 'hi') -> bool:\n"
            "        return True\n"
        )
        ctx = extract_ast_context_from_source(source, target_func="bar")
        assert "self" in ctx.signature
        assert "x: int" in ctx.signature
        assert "-> bool" in ctx.signature

    def test_import_with_alias(self) -> None:
        """Import aliases are preserved."""
        source = "import numpy as np\n"
        ctx = extract_ast_context_from_source(source)
        assert "import numpy as np" in ctx.imports

    def test_from_import_multiple(self) -> None:
        """From-import with multiple names."""
        source = "from os.path import join, exists\n"
        ctx = extract_ast_context_from_source(source)
        assert any("join" in i and "exists" in i for i in ctx.imports)

    def test_star_import(self) -> None:
        """Star import is captured."""
        source = "from math import *\n"
        ctx = extract_ast_context_from_source(source)
        assert any("*" in i for i in ctx.imports)

    def test_default_argument_values(self) -> None:
        """Default argument values appear in the signature."""
        source = "def f(a: int, b: str = 'hello', c: float = 3.14) -> None:\n    pass\n"
        ctx = extract_ast_context_from_source(source, target_func="f")
        assert "'hello'" in ctx.signature or "hello" in ctx.signature
        assert "3.14" in ctx.signature


# ---------------------------------------------------------------------------
# extract_ast_context (filesystem) tests
# ---------------------------------------------------------------------------


class TestExtractFromFile:
    """Tests for extract_ast_context reading from the filesystem."""

    def test_sample_source(self) -> None:
        """Parses the fixture file and extracts expected info."""
        ctx = extract_ast_context(SAMPLE_SOURCE, target_func="validate_input")
        assert "def validate_input" in ctx.signature
        assert any("import os" in i for i in ctx.imports)
        assert any("from pathlib" in i for i in ctx.imports)
        # validate_input has local annotated vars
        assert ctx.known_vars.get("user_id") == "Optional[int]"
        assert ctx.known_vars.get("name") == "str"

    def test_global_vars_from_fixture(self) -> None:
        """Global annotated variables from the fixture are found."""
        ctx = extract_ast_context(SAMPLE_SOURCE)
        assert ctx.known_vars.get("GLOBAL_CONFIG") == "dict"
        assert ctx.known_vars.get("MAX_RETRIES") == "int"

    def test_file_not_found(self) -> None:
        """Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            extract_ast_context("/nonexistent/file.py")

    def test_class_method(self) -> None:
        """Class method signatures are extracted."""
        ctx = extract_ast_context(SAMPLE_SOURCE, target_func="_process_item")
        assert "def _process_item" in ctx.signature
        assert ctx.known_vars.get("key") == "str"
        assert ctx.known_vars.get("result") == "dict"
