"""I/O utilities for reading input from various sources."""

from __future__ import annotations

import sys
from pathlib import Path


def _looks_like_path(source: str) -> bool:
    """Heuristic: does *source* look like a filesystem path?"""
    # Paths typically contain / or end with common log/code extensions
    if "/" in source and not source.startswith("Traceback"):
        return True
    return source.endswith((".log", ".txt", ".out", ".err", ".py", ".json"))


def read_input(source: str) -> str:
    """Read text input from a file path, stdin marker, or raw string.

    Resolution order:
    1. If *source* is ``"-"`` or ``"/dev/stdin"``, read from stdin.
    2. If *source* is an existing file path, read its contents.
    3. Otherwise treat *source* as a raw string and return it directly.

    Args:
        source: File path, ``"-"``, or raw text.

    Returns:
        The resolved text content.

    Raises:
        FileNotFoundError: If *source* looks like a path but does not exist.
    """
    if source == "-" or source == "/dev/stdin":
        return sys.stdin.read()

    path = Path(source)
    if path.exists() and path.is_file():
        return path.read_text(encoding="utf-8")

    # If it looks like a plausible file path but doesn't exist, raise.
    # Multi-line strings are never file paths (they're raw traceback text).
    if "\n" not in source and _looks_like_path(source):
        raise FileNotFoundError(f"Input file not found: {source}")

    return source


def write_output(data: str, output_path: str | None = None) -> None:
    """Write *data* to a file or stdout.

    Args:
        data: Text content to write.
        output_path: If provided, write to this file; otherwise print to stdout.
    """
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")
    else:
        print(data)
