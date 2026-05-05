"""AST-based context extractor for Python source files.

Uses the built-in ``ast`` module to parse source code and extract
signatures, imports, and variable annotations relevant to a traceback.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ASTContext(BaseModel):
    """Structured context extracted from a Python source file via AST.

    Attributes:
        signature: Function or method signature where the error occurred.
        imports: List of import statements in the file.
        known_vars: Mapping of variable names to their type annotations.
    """

    signature: str = Field(
        default="",
        description="Full signature of the function where the error occurred",
    )
    imports: list[str] = Field(
        default_factory=list,
        description="Import statements found in the source file",
    )
    known_vars: dict[str, str] = Field(
        default_factory=dict,
        description="Variable name → type annotation string",
    )

    def to_context_dict(self) -> dict[str, Any]:
        """Return a dictionary suitable for downstream context injection."""
        return {
            "signature": self.signature,
            "imports": self.imports,
            "known_vars": self.known_vars,
        }


def extract_ast_context(
    source_path: str | Path,
    target_line: int = 0,
    target_func: str | None = None,
) -> ASTContext:
    """Extract AST context from a Python source file.

    Parses the file and returns information about imports, the function
    containing *target_line* (or named *target_func*), and annotated
    variables visible at that point.

    Args:
        source_path: Path to the ``.py`` file to analyse.
        target_line: 1-based line number of the error (0 = no specific line).
        target_func: Optional function name to look up directly.

    Returns:
        An ``ASTContext`` with the extracted information.

    Raises:
        FileNotFoundError: If *source_path* does not exist.
        SyntaxError: If the file cannot be parsed as valid Python.
    """
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")

    source_text = path.read_text(encoding="utf-8")
    return extract_ast_context_from_source(
        source_text,
        filename=str(path),
        target_line=target_line,
        target_func=target_func,
    )


def extract_ast_context_from_source(
    source: str,
    filename: str = "<unknown>",
    target_line: int = 0,
    target_func: str | None = None,
) -> ASTContext:
    """Extract AST context from a Python source string.

    This is the core implementation that works on raw source text,
    making it easy to test without touching the filesystem.

    Args:
        source: Python source code as a string.
        filename: Filename to use for error messages.
        target_line: 1-based line number of the error.
        target_func: Optional function name to look up directly.

    Returns:
        An ``ASTContext`` with the extracted information.

    Raises:
        SyntaxError: If *source* cannot be parsed as valid Python.
    """
    tree = ast.parse(source, filename=filename)

    imports = _extract_imports(tree)
    known_vars = _extract_global_vars(tree)

    # Find the target function
    func_node = _find_target_function(tree, target_line, target_func)
    if func_node is not None:
        signature = _build_signature(func_node)
        # Merge function-local annotated variables
        local_vars = _extract_local_vars(func_node)
        known_vars.update(local_vars)
    else:
        signature = ""

    return ASTContext(
        signature=signature,
        imports=imports,
        known_vars=known_vars,
    )


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _extract_imports(tree: ast.Module) -> list[str]:
    """Extract all import statements from the module."""
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    imports.append(f"import {alias.name} as {alias.asname}")
                else:
                    imports.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = []
            for alias in node.names:
                if alias.asname:
                    names.append(f"{alias.name} as {alias.asname}")
                else:
                    names.append(alias.name)
            imports.append(f"from {module} import {', '.join(names)}")
    return imports


def _extract_global_vars(tree: ast.Module) -> dict[str, str]:
    """Extract top-level variable assignments with type annotations."""
    vars_dict: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            annotation = _unparse_annotation(node.annotation)
            if annotation:
                vars_dict[node.target.id] = annotation
    return vars_dict


def _extract_local_vars(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, str]:
    """Extract annotated variable assignments inside a function."""
    vars_dict: dict[str, str] = {}
    for node in ast.walk(func_node):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            annotation = _unparse_annotation(node.annotation)
            if annotation:
                vars_dict[node.target.id] = annotation
    return vars_dict


def _find_target_function(
    tree: ast.Module,
    target_line: int,
    target_func: str | None,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Locate the function containing *target_line* or named *target_func*."""
    candidates: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            candidates.append(node)

    # Prefer name match
    if target_func:
        for node in candidates:
            if node.name == target_func:
                return node

    # Fall back to line-range match
    if target_line > 0:
        best: ast.FunctionDef | ast.AsyncFunctionDef | None = None
        best_size = float("inf")
        for node in candidates:
            start = node.lineno
            end = getattr(node, "end_lineno", start)
            if start <= target_line <= end:
                size = end - start
                if size < best_size:
                    best = node
                    best_size = size
        if best is not None:
            return best

    return None


def _build_signature(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Build a human-readable function signature string."""
    parts: list[str] = []
    prefix = "async def " if isinstance(func_node, ast.AsyncFunctionDef) else "def "
    parts.append(prefix + func_node.name + "(")

    # Arguments
    args = func_node.args
    arg_strs: list[str] = []

    # positional-only args (Python 3.8+)
    for i, arg in enumerate(args.posonlyargs):
        s = arg.arg
        if arg.annotation:
            s += ": " + _unparse_annotation(arg.annotation)
        arg_strs.append(s)
    if args.posonlyargs:
        arg_strs.append("/")

    # regular args
    defaults_offset = len(args.args) - len(args.defaults)
    for i, arg in enumerate(args.args):
        if arg.arg == "self" or arg.arg == "cls":
            arg_strs.append(arg.arg)
            continue
        s = arg.arg
        if arg.annotation:
            s += ": " + _unparse_annotation(arg.annotation)
        default_idx = i - defaults_offset
        if default_idx >= 0:
            s += " = " + _unparse_node(args.defaults[default_idx])
        arg_strs.append(s)

    # *args
    if args.vararg:
        s = "*" + args.vararg.arg
        if args.vararg.annotation:
            s += ": " + _unparse_annotation(args.vararg.annotation)
        arg_strs.append(s)

    # keyword-only args
    for i, arg in enumerate(args.kwonlyargs):
        s = arg.arg
        if arg.annotation:
            s += ": " + _unparse_annotation(arg.annotation)
        if i < len(args.kw_defaults) and args.kw_defaults[i] is not None:
            s += " = " + _unparse_node(args.kw_defaults[i])
        arg_strs.append(s)

    # **kwargs
    if args.kwarg:
        s = "**" + args.kwarg.arg
        if args.kwarg.annotation:
            s += ": " + _unparse_annotation(args.kwarg.annotation)
        arg_strs.append(s)

    parts.append(", ".join(arg_strs))
    parts.append(")")

    # Return annotation
    if func_node.returns:
        parts.append(" -> " + _unparse_annotation(func_node.returns))

    return "".join(parts)


def _unparse_annotation(node: ast.expr) -> str:
    """Convert an annotation AST node to a string."""
    try:
        return ast.unparse(node)
    except AttributeError:
        # Python < 3.9 fallback
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return _unparse_annotation(node.value) + "." + node.attr
        if isinstance(node, ast.Subscript):
            return _unparse_annotation(node.value) + "[" + _unparse_annotation(node.slice) + "]"
        if isinstance(node, ast.Tuple):
            return ", ".join(_unparse_annotation(e) for e in node.elts)
        return "<unknown>"


def _unparse_node(node: ast.expr) -> str:
    """Convert an expression AST node to a short string representation."""
    try:
        return ast.unparse(node)
    except AttributeError:
        if isinstance(node, ast.Constant):
            return repr(node.value)
        if isinstance(node, ast.Name):
            return node.id
        return "..."
