"""Parser for Python-style stack traces and tracebacks."""

from __future__ import annotations

import re
from typing import ClassVar

from log2repro.parsers.base import BaseParser, ParsedTrace

# Matches a traceback header line: "Traceback (most recent call last):"
_RE_TRACEBACK_HEADER: re.Pattern[str] = re.compile(
    r"^Traceback \(most recent call last\):", re.MULTILINE
)

# Matches a call-site line: '  File "path.py", line 42, in func_name'
_RE_CALL_SITE: re.Pattern[str] = re.compile(
    r'^\s*File "(?P<file>[^"]+)",\s*line\s+(?P<line>\d+),\s*in\s+(?P<func>\S+)',
    re.MULTILINE,
)

# Matches the final exception line: 'ExceptionType: message' or bare 'ExceptionType'.
#
# Two alternatives:
#   exc_type  — dotted module paths, e.g. "ssl.SSLCertVerificationError",
#               "numpy.core._exceptions._UFuncNoLoopError"
#   exc_type2 — bare exception names with mixed case, e.g. "RuntimeError"
#
# Bare all-caps words like "DETAIL", "HINT", "SQL" are excluded because they
# require at least one lowercase letter after the initial uppercase.
_RE_EXCEPTION_LINE: re.Pattern[str] = re.compile(
    r"^(?P<exc_type>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\.[A-Z_]\w*"
    r"|(?P<exc_type2>[A-Z]\w*[a-z]\w*))(?::\s*(?P<msg>.+))?$",
    re.MULTILINE,
)

# Matches variable assignment or reference patterns in source lines
# e.g. "result = foo.bar(x, y)" or "if obj.attr is None:"
_RE_VAR_PATTERN: re.Pattern[str] = re.compile(
    r"\b(?P<var>[a-zA-Z_][a-zA-Z0-9_]*)\b"
)

# Common keywords/names to exclude from extracted variables
_STOPWORDS: frozenset[str] = frozenset({
    "self", "cls", "None", "True", "False", "and", "or", "not", "is", "in",
    "if", "else", "elif", "for", "while", "return", "def", "class", "import",
    "from", "with", "as", "try", "except", "finally", "raise", "yield",
    "lambda", "pass", "break", "continue", "del", "global", "nonlocal",
    "assert", "print", "len", "range", "int", "str", "float", "list",
    "dict", "set", "tuple", "bool", "type", "object", "super", "isinstance",
})


class StacktraceParser(BaseParser):
    """Parse Python-style tracebacks into structured ``ParsedTrace`` objects.

    Supports the standard format produced by Python's ``traceback`` module,
    including chained exceptions (``During handling ...`` / ``The above ...``).

    Example::

        parser = StacktraceParser()
        traces = parser.parse(open("error.log").read())
        for t in traces:
            print(t.error, t.file, t.line)
    """

    # Chained exception markers
    _CHAIN_PREFIXES: ClassVar[tuple[str, ...]] = (
        "During handling of the above exception",
        "The above exception was the direct cause",
    )

    def can_parse(self, text: str) -> bool:
        """Check whether *text* contains a Python traceback."""
        return bool(_RE_TRACEBACK_HEADER.search(text))

    def parse(self, text: str) -> list[ParsedTrace]:
        """Extract ``ParsedTrace`` objects from traceback text.

        Splits on traceback headers so chained exceptions produce multiple
        traces.  Each trace's call chain is preserved in ``chain``.

        Args:
            text: Raw traceback text (may contain chained exceptions).

        Returns:
            List of parsed traces, one per distinct exception block.
        """
        blocks = self._split_tracebacks(text)
        results: list[ParsedTrace] = []
        for block in blocks:
            trace = self._parse_single_block(block)
            if trace is not None:
                results.append(trace)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _split_tracebacks(self, text: str) -> list[str]:
        """Split *text* into individual traceback blocks."""
        parts = _RE_TRACEBACK_HEADER.split(text)
        # The first part is anything before the first "Traceback ..."
        # (often empty or a preamble).  Re-attach the header to each block.
        blocks: list[str] = []
        for part in parts[1:]:  # skip preamble
            block = "Traceback (most recent call last):\n" + part
            # Cut off chained-exception preamble if present
            for prefix in self._CHAIN_PREFIXES:
                idx = block.find(prefix)
                if idx != -1:
                    block = block[:idx]
            blocks.append(block.strip())
        return blocks

    def _parse_single_block(self, block: str) -> ParsedTrace | None:
        """Parse a single traceback block into a ``ParsedTrace``."""
        call_sites = list(_RE_CALL_SITE.finditer(block))
        if not call_sites:
            return None

        # The last call site is where the exception originated
        origin = call_sites[-1]
        source_file: str = origin.group("file")
        line_no: int = int(origin.group("line"))

        # Extract the exception type and message.
        # Walk backward through the block looking for a non-indented line that
        # matches the exception pattern.  Indented lines (continuation text like
        # "email", "  field required") are skipped.
        lines = block.rstrip().splitlines()
        exc_type = "UnknownError"
        exc_msg = ""
        for line in reversed(lines):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("File ") or stripped.startswith("Traceback"):
                continue
            # Only match non-indented lines (exception headers are never indented)
            if not line[0].isspace():
                m = _RE_EXCEPTION_LINE.match(stripped)
                if m:
                    exc_type = m.group("exc_type") or m.group("exc_type2")
                    exc_msg = (m.group("msg") or "").strip()
                    break

        error_str = f"{exc_type}: {exc_msg}" if exc_msg else exc_type

        # Build the call chain
        chain: list[str] = []
        for cs in call_sites:
            f = cs.group("file")
            fn = cs.group("func")
            ln = cs.group("line")
            chain.append(f"{f}:{fn}:{ln}")

        # Extract context variables from source lines (lines starting with whitespace
        # that are not call-site lines)
        context_vars = self._extract_context_vars(block, call_sites)

        return ParsedTrace(
            file=source_file,
            line=line_no,
            error=error_str,
            context_vars=sorted(context_vars),
            chain=chain,
        )

    @staticmethod
    def _extract_context_vars(
        block: str,
        call_sites: list[re.Match[str]],
    ) -> set[str]:
        """Extract variable names from source code lines in the traceback.

        Looks at indented lines that appear between call-site lines (these are
        the actual source code lines Python displays in tracebacks).
        """
        lines = block.splitlines()
        # Collect line indices that are call-site lines
        call_site_indices: set[int] = set()
        for cs in call_sites:
            # Find the line index by matching the start position
            pos = cs.start()
            idx = block[:pos].count("\n")
            call_site_indices.add(idx)

        variables: set[str] = set()
        for i, line in enumerate(lines):
            # Source code lines are indented and not call-site or exception lines
            if i in call_site_indices:
                continue
            stripped = line.strip()
            if not stripped:
                continue
            # Skip traceback header and exception lines
            if stripped.startswith("Traceback") or _RE_EXCEPTION_LINE.match(stripped):
                continue
            # Heuristic: source lines shown by Python are indented with spaces
            # and contain actual code (not just "File ..." lines)
            if line.startswith("    ") and not line.strip().startswith('"'):
                for m in _RE_VAR_PATTERN.finditer(stripped):
                    name = m.group("var")
                    if name not in _STOPWORDS and len(name) > 1:
                        variables.add(name)

        return variables
