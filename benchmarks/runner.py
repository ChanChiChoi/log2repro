"""Benchmark runner: executes prompt variants against trace fixtures.

Usage::

    # Run from project root
    uv run python -m benchmarks.runner

    # With custom run count
    uv run python -m benchmarks.runner --runs 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from benchmarks.mock_responses import generate_mock_response
from benchmarks.prompt_variants import PROMPT_VARIANTS, VARIANT_LABELS
from benchmarks.report import VariantResult, generate_per_trace_table, generate_report
from benchmarks.validator import validate_response
from log2repro.parsers.stacktrace import StacktraceParser

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

TRACE_FIXTURES: dict[str, Path] = {
    "sample":       FIXTURES_DIR / "trace_sample.log",
    "fastapi":      FIXTURES_DIR / "trace_fastapi.log",
    "pytorch":      FIXTURES_DIR / "trace_pytorch.log",
    "sqlalchemy":   FIXTURES_DIR / "trace_sqlalchemy.log",
    "requests":     FIXTURES_DIR / "trace_requests.log",
}

DEFAULT_RUNS = 10


def run_benchmark(num_runs: int = DEFAULT_RUNS) -> tuple[list[VariantResult], dict[str, list[VariantResult]]]:
    """Execute the full benchmark suite.

    Args:
        num_runs: Number of runs per (variant, trace) pair.

    Returns:
        A tuple of (overall_results, per_trace_results).
    """
    parser = StacktraceParser()

    # Parse all fixtures
    traces = {}
    for name, path in TRACE_FIXTURES.items():
        text = path.read_text()
        parsed = parser.parse(text)
        if parsed:
            traces[name] = parsed[0]
        else:
            print(f"WARNING: Could not parse {name}", file=sys.stderr)

    # Accumulate results per variant
    overall: dict[str, VariantResult] = {}
    per_trace: dict[str, list[VariantResult]] = {}

    for variant_key, system_prompt in PROMPT_VARIANTS.items():
        vr = VariantResult(
            variant=variant_key,
            label=VARIANT_LABELS.get(variant_key, variant_key),
            total_runs=0,
        )

        for trace_name, trace in traces.items():
            trace_vr = VariantResult(
                variant=variant_key,
                label=VARIANT_LABELS.get(variant_key, variant_key),
                total_runs=0,
            )

            for run_idx in range(num_runs):
                # Generate mock response
                mock = generate_mock_response(variant_key, trace, run_idx)
                response_text = mock["response_text"]
                tokens = mock["tokens_used"]

                # Validate
                validation = validate_response(response_text, trace)

                # Accumulate
                for acc in (vr, trace_vr):
                    acc.total_runs += 1
                    acc.total_tokens += tokens
                    if validation.triggers_error or mock["triggered"]:
                        acc.trigger_count += 1
                    if validation.hallucinated or mock["hallucinated"]:
                        acc.hallucination_count += 1
                    if validation.all_files_present:
                        acc.file_completeness_count += 1

            per_trace.setdefault(trace_name, []).append(trace_vr)

        overall[variant_key] = vr

    # Order by variant key
    ordered = [overall[k] for k in sorted(overall.keys())]
    return ordered, per_trace


def main() -> None:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description="System Prompt Benchmark")
    ap.add_argument("--runs", type=int, default=DEFAULT_RUNS, help="Runs per variant per trace")
    args = ap.parse_args()

    print(f"Running benchmark: {len(PROMPT_VARIANTS)} variants × "
          f"{len(TRACE_FIXTURES)} traces × {args.runs} runs\n")

    overall, per_trace = run_benchmark(args.runs)

    # Overall report
    print(generate_report(overall))

    # Per-trace breakdown
    print(generate_per_trace_table(per_trace))
    print()

    # Recommendation
    best_trigger = max(overall, key=lambda r: r.trigger_rate)
    best_halluc = min(overall, key=lambda r: r.hallucination_rate)
    best_speed = min(overall, key=lambda r: r.avg_tokens)

    print("## Recommendation")
    print()
    print(f"- **Best trigger rate**: {best_trigger.variant} ({best_trigger.trigger_rate:.0f}%)")
    print(f"- **Lowest hallucination**: {best_halluc.variant} ({best_halluc.hallucination_rate:.0f}%)")
    print(f"- **Fastest (fewest tokens)**: {best_speed.variant} ({best_speed.avg_tokens:.0f} tok/run)")
    print()


if __name__ == "__main__":
    main()
