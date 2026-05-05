"""Base parser interface and core data models for log parsing."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class ParsedTrace(BaseModel):
    """Structured representation of a parsed error traceback.

    Attributes:
        file: Source file path where the error occurred.
        line: Line number of the error.
        error: Error type and message (e.g. "ValueError: invalid literal").
        context_vars: Variable names extracted from the error context.
        chain: Call chain entries as "file:func:line" strings.
    """

    file: str = Field(description="Source file path where the error occurred")
    line: int = Field(description="Line number of the error", ge=0)
    error: str = Field(description="Error type and message")
    context_vars: list[str] = Field(
        default_factory=list,
        description="Variable names extracted from the error context",
    )
    chain: list[str] = Field(
        default_factory=list,
        description='Call chain entries as "file:func:line" strings',
    )

    def to_context_dict(self) -> dict[str, Any]:
        """Return a dictionary suitable for downstream context injection."""
        return {
            "file": self.file,
            "line": self.line,
            "error": self.error,
            "context_vars": self.context_vars,
            "chain": self.chain,
        }


class BaseParser(ABC):
    """Abstract base class for all log parsers.

    Subclasses must implement ``parse`` to return one or more ``ParsedTrace``
    objects from raw log text.
    """

    @abstractmethod
    def parse(self, text: str) -> list[ParsedTrace]:
        """Parse raw log text and extract structured trace information.

        Args:
            text: Raw log or traceback text.

        Returns:
            A list of ``ParsedTrace`` objects, one per distinct error found.
        """
        ...

    def can_parse(self, text: str) -> bool:
        """Quick heuristic check: can this parser handle the given text?

        Args:
            text: Raw log text.

        Returns:
            ``True`` if this parser believes it can extract useful info.
        """
        return bool(text and text.strip())
