"""Parser for Sentry JSON export format.

Extracts structured trace information from Sentry issue JSON payloads,
including exception stacktrace, tags, and contextual metadata.

TODO(D2): Implement full Sentry JSON parsing with:
- ``sentry.interfaces.Exception`` extraction
- Breadcrumb timeline parsing
- Tag & user context extraction
"""

from __future__ import annotations

from typing import Any

from log2repro.parsers.base import BaseParser, ParsedTrace


class SentryParser(BaseParser):
    """Parse Sentry JSON issue exports into ``ParsedTrace`` objects.

    Expects JSON with at least ``exception.values`` or ``stacktrace``
    fields as produced by the Sentry API.

    Example::

        parser = SentryParser()
        with open("sentry_issue.json") as f:
            traces = parser.parse(f.read())
    """

    def can_parse(self, text: str) -> bool:
        """Check whether *text* looks like Sentry JSON."""
        text = text.strip()
        if not text.startswith("{"):
            return False
        # Quick heuristic: look for Sentry-specific keys
        return '"exception"' in text or '"stacktrace"' in text or '"culprit"' in text

    def parse(self, text: str) -> list[ParsedTrace]:
        """Parse Sentry JSON into ``ParsedTrace`` objects.

        Args:
            text: JSON string from Sentry API or export.

        Returns:
            List of parsed traces (one per exception in the chain).
        """
        import json

        try:
            data: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError:
            return []

        results: list[ParsedTrace] = []

        # Try exception.values format first
        exception = data.get("exception", {})
        values = exception.get("values", [])
        if not values:
            # Fallback: single stacktrace at top level
            st = data.get("stacktrace", {})
            if st:
                values = [{"stacktrace": st, "type": data.get("type", "UnknownError")}]

        for exc_val in values:
            trace = self._parse_exception_value(exc_val)
            if trace is not None:
                results.append(trace)

        return results

    @staticmethod
    def _parse_exception_value(exc_val: dict[str, Any]) -> ParsedTrace | None:
        """Convert a single Sentry exception value to a ``ParsedTrace``."""
        st = exc_val.get("stacktrace", {})
        frames = st.get("frames", [])
        if not frames:
            return None

        # Sentry frames are ordered oldest-first; the last frame is the origin
        origin = frames[-1]
        source_file = origin.get("filename", origin.get("abs_path", "<unknown>"))
        line_no = origin.get("lineno", 0)
        exc_type = exc_val.get("type", "UnknownError")
        exc_value = exc_val.get("value", "")
        error_str = f"{exc_type}: {exc_value}" if exc_value else exc_type

        chain: list[str] = []
        for frame in frames:
            fn = frame.get("function", "<unknown>")
            f = frame.get("filename", "<unknown>")
            ln = frame.get("lineno", 0)
            chain.append(f"{f}:{fn}:{ln}")

        # Extract context vars from the origin frame's context_line
        context_vars: list[str] = []
        context_line = origin.get("context_line", "")
        if context_line:
            import re
            for m in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", context_line):
                name = m.group(1)
                if len(name) > 1 and name not in {"if", "in", "is", "or", "and", "not", "for", "def", "class", "return", "None", "True", "False"}:
                    context_vars.append(name)

        # Also extract variable names from Sentry frame vars dict
        for frame in frames:
            frame_vars = frame.get("vars", {})
            if isinstance(frame_vars, dict):
                context_vars.extend(frame_vars.keys())

        return ParsedTrace(
            file=source_file,
            line=line_no,
            error=error_str,
            context_vars=sorted(set(context_vars)),
            chain=chain,
        )
