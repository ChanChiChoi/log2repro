"""Parser for CI/CD log output (GitHub Actions, GitLab CI, etc.).

Extracts Python tracebacks from noisy CI logs that contain interleaved
build output, ANSI escape codes, and multi-step job logs.

TODO(D2): Implement full CI log parsing with:
- ANSI escape code stripping
- GitHub Actions step boundary detection
- GitLab CI section parsing
- Jest / pytest output integration
"""

from __future__ import annotations

import re

from log2repro.parsers.base import BaseParser, ParsedTrace
from log2repro.parsers.stacktrace import StacktraceParser

# Matches ANSI escape sequences
_RE_ANSI: re.Pattern[str] = re.compile(r"\x1b\[[0-9;]*m")


class CILogParser(BaseParser):
    """Parse CI log output and extract Python tracebacks.

    Handles noisy CI output by stripping ANSI codes and delegating
    to :class:`StacktraceParser` for actual traceback extraction.

    Example::

        parser = CILogParser()
        with open("github_actions.log") as f:
            traces = parser.parse(f.read())
    """

    def __init__(self) -> None:
        self._stack_parser = StacktraceParser()

    def can_parse(self, text: str) -> bool:
        """Check whether *text* contains a traceback (after ANSI stripping)."""
        cleaned = _RE_ANSI.sub("", text)
        return self._stack_parser.can_parse(cleaned)

    def parse(self, text: str) -> list[ParsedTrace]:
        """Extract traces from CI log text.

        Strips ANSI codes, splits on common CI step boundaries, and
        delegates traceback extraction to :class:`StacktraceParser`.

        Args:
            text: Raw CI log text (may contain ANSI codes).

        Returns:
            List of parsed traces found in the log.
        """
        # Strip ANSI escape codes
        cleaned = _RE_ANSI.sub("", text)

        # Try full-text parse first (most common case)
        traces = self._stack_parser.parse(cleaned)
        if traces:
            return traces

        # Fallback: split on CI step boundaries and try each section
        sections = self._split_ci_sections(cleaned)
        results: list[ParsedTrace] = []
        for section in sections:
            results.extend(self._stack_parser.parse(section))

        return results

    @staticmethod
    def _split_ci_sections(text: str) -> list[str]:
        """Split CI log into sections by common step markers."""
        # GitHub Actions: ##[group], ##[error], Run <command>
        # GitLab CI: section_start, section_end
        # Generic: lines starting with "Step ", "ERROR", "FAIL"
        boundary_pattern = re.compile(
            r"(?:^##\[|^Run\s|^Step\s|^ERROR|^FAIL|^section_start)",
            re.MULTILINE,
        )
        splits = boundary_pattern.split(text)
        # Return non-empty sections
        [s.strip() for s in splits if s.strip()]
        # Since we split on boundaries, each section may or may not contain
        # a traceback. Return all non-trivial sections.
        return [s for s in splits if len(s) > 50]
