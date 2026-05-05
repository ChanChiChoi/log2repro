"""Data models for log2repro analysis and reproduction results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FixRecommendation:
    """A single fix recommendation with confidence ranking.

    Attributes:
        description: Human-readable description of the fix.
        confidence: Confidence level — ``"high"``, ``"medium"``, or ``"low"``.
        code_snippet: Optional code snippet demonstrating the fix.
    """

    description: str
    confidence: str = "medium"  # "high" | "medium" | "low"
    code_snippet: str = ""


@dataclass
class AnalysisResult:
    """Structured result of root cause analysis.

    Attributes:
        root_cause: Identified root cause of the error.
        error_type: Classification of the error type.
        affected_code_path: Code path where the error originates.
        impact: Description of the error's impact.
        recommendations: List of fix recommendations sorted by confidence.
        raw_markdown: Full raw Markdown response from the LLM.
    """

    root_cause: str = ""
    error_type: str = ""
    affected_code_path: str = ""
    impact: str = ""
    recommendations: list[FixRecommendation] = field(default_factory=list)
    raw_markdown: str = ""
