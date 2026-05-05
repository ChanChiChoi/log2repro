"""Benchmark report generator.

Produces a Markdown table summarising prompt variant performance.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VariantResult:
    """Aggregated results for one prompt variant across all runs.

    Attributes:
        variant: Prompt variant key (e.g. ``"P1_SPEED"``).
        label: Human-readable label.
        total_runs: Total number of benchmark runs.
        trigger_count: Number of runs that reproduced the error.
        hallucination_count: Number of runs with hallucinated content.
        total_tokens: Sum of tokens across all runs.
        file_completeness_count: Number of runs with all 3 files present.
    """

    variant: str = ""
    label: str = ""
    total_runs: int = 0
    trigger_count: int = 0
    hallucination_count: int = 0
    total_tokens: int = 0
    file_completeness_count: int = 0

    @property
    def trigger_rate(self) -> float:
        """Success trigger rate as a percentage."""
        return (self.trigger_count / self.total_runs * 100) if self.total_runs else 0.0

    @property
    def hallucination_rate(self) -> float:
        """Hallucination rate as a percentage."""
        return (self.hallucination_count / self.total_runs * 100) if self.total_runs else 0.0

    @property
    def avg_tokens(self) -> float:
        """Average tokens per run."""
        return (self.total_tokens / self.total_runs) if self.total_runs else 0.0

    @property
    def file_completeness_rate(self) -> float:
        """Percentage of runs with all 3 files present."""
        return (self.file_completeness_count / self.total_runs * 100) if self.total_runs else 0.0


def generate_report(results: list[VariantResult]) -> str:
    """Generate a Markdown report from benchmark results.

    Args:
        results: One ``VariantResult`` per prompt variant.

    Returns:
        A Markdown-formatted report string.
    """
    lines: list[str] = []
    lines.append("# System Prompt Benchmark Report")
    lines.append("")
    lines.append("## Results Summary")
    lines.append("")
    lines.append(
        "| Prompt | 侧重 | 成功率 ↑ | 幻觉率 ↓ | Token/次 ↓ | 文件完整率 |"
    )
    lines.append(
        "|--------|------|---------|---------|-----------|-----------|"
    )

    for r in results:
        # Extract focus from label
        focus = r.label.split(" ", 1)[-1] if " " in r.label else r.label
        lines.append(
            f"| {r.variant} | {focus} | "
            f"{r.trigger_rate:.0f}% | "
            f"{r.hallucination_rate:.0f}% | "
        f"{r.avg_tokens:.0f} | "
            f"{r.file_completeness_rate:.0f}% |"
        )

    lines.append("")
    lines.append("## Per-Trace Breakdown")
    lines.append("")

    return "\n".join(lines)


def generate_per_trace_table(
    trace_results: dict[str, list[VariantResult]],
) -> str:
    """Generate a per-trace breakdown table.

    Args:
        trace_results: Mapping of trace name → list of VariantResults.

    Returns:
        Markdown table string.
    """
    lines: list[str] = []
    lines.append("| Trace | Prompt | 触发 | 幻觉 | Token |")
    lines.append("|-------|--------|------|------|-------|")

    for trace_name, variants in trace_results.items():
        for i, r in enumerate(variants):
            name_col = trace_name if i == 0 else ""
            trigger = "✅" if r.trigger_count > 0 else "❌"
            halluc = "⚠️" if r.hallucination_count > 0 else "✅"
            lines.append(
                f"| {name_col} | {r.variant} | {trigger} | {halluc} | {r.avg_tokens:.0f} |"
            )

    return "\n".join(lines)
