"""Mock LLM responses for benchmark testing.

Each prompt variant produces responses with different quality characteristics:
- P1 (speed): short, occasionally misses files, no mock_data
- P2 (minimal): very short, high hallucination risk
- P3 (balanced): medium, moderate quality
- P4 (complete): long, thorough, few hallucinations
- P5 (security): long, zero dangerous patterns, occasionally too cautious
"""

from __future__ import annotations

import hashlib
from typing import Any

from log2repro.parsers.base import ParsedTrace

# ---------------------------------------------------------------------------
# Quality profiles per prompt variant
# ---------------------------------------------------------------------------

# (trigger_rate, hallucination_rate, avg_response_chars)
# trigger_rate: probability the response correctly reproduces the error
# hallucination_rate: probability of inventing a non-existent library/variable
# avg_response_chars: typical response length (used for token estimation)
_QUALITY_PROFILES: dict[str, tuple[float, float, int]] = {
    "P1_SPEED":    (0.70, 0.15, 800),   # fast but sloppy
    "P2_MINIMAL":  (0.55, 0.25, 500),   # very fast, high hallucination
    "P3_BALANCED": (0.85, 0.10, 1500),  # good balance
    "P4_COMPLETE": (0.90, 0.03, 2500),  # thorough, rare hallucination
    "P5_SECURITY": (0.80, 0.02, 2200),  # safe, occasionally over-cautious
}


def _seeded_choice(variant: str, trace_file: str, run_idx: int, threshold: float) -> bool:
    """Deterministic yes/no decision based on hash seed."""
    seed = f"{variant}:{trace_file}:{run_idx}"
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16) % 10000
    return (h / 10000.0) < threshold


def _estimate_tokens(char_count: int) -> int:
    """Rough estimate: 1 token ≈ 4 characters."""
    return char_count // 4


# ---------------------------------------------------------------------------
# Response templates
# ---------------------------------------------------------------------------

def _build_reproduce_py(
    trace: ParsedTrace,
    *,
    with_mock_data: bool = True,
    with_type_annotations: bool = False,
    with_security_checks: bool = False,
    with_few_shot_comments: bool = False,
    use_hallucinated_lib: bool = False,
    missing_requirements: bool = False,
) -> str:
    """Build a mock reproduce.py content."""
    error_type = trace.error.split(":")[0].strip()
    error_msg = trace.error.split(":", 1)[1].strip() if ":" in trace.error else ""

    lines: list[str] = []

    # Docstring
    lines.append(f'"""Reproduce {trace.error}."""')
    lines.append("")

    # Imports
    lines.append("from unittest.mock import MagicMock, patch")
    if use_hallucinated_lib:
        lines.append("import nonexistent_hallucinated_lib  # HALLUCINATION")
    if with_security_checks:
        lines.append("# Security: no eval/exec/subprocess imported")
    lines.append("")
    lines.append("")

    # Function
    if with_type_annotations:
        lines.append("def trigger_error(data: dict, config: dict | None = None) -> None:")
    else:
        lines.append("def trigger_error(data, config=None):")
    lines.append(f'    """Trigger {error_type}."""')

    if with_few_shot_comments:
        lines.append(f"    # This line causes {error_type} because the value is invalid")
        lines.append("    # Mock: external API returns bad data")

    if use_hallucinated_lib:
        lines.append("    result = nonexistent_hallucinated_lib.process(data)")
    else:
        if "KeyError" in error_type:
            lines.append("    return data[\"missing_key\"]")
        elif "ValueError" in error_type:
            lines.append("    if data.get(\"value\") is None:")
            lines.append(f'        raise ValueError("{error_msg}")')
        elif "TypeError" in error_type:
            lines.append("    result = data + 1  # str + int")
        elif "AttributeError" in error_type:
            lines.append("    obj = MagicMock()")
            lines.append("    del obj.attr")
            lines.append("    return obj.attr")
        elif "RuntimeError" in error_type:
            lines.append("    raise RuntimeError(\"mat1 and mat2 shapes cannot be multiplied\")")
        elif "ConnectionRefused" in error_type:
            lines.append("    raise ConnectionRefusedError(\"[Errno 111] Connection refused\")")
        elif "SSLError" in error_type or "SSLCertVerification" in error_type:
            lines.append("    import ssl")
            lines.append("    raise ssl.SSLCertVerificationError(\"certificate verify failed\")")
        elif "IntegrityError" in error_type:
            lines.append("    raise Exception(\"duplicate key value violates unique constraint\")")
        elif "NoResultFound" in error_type:
            lines.append("    raise Exception(\"No row was found when one was required\")")
        elif "ValidationError" in error_type:
            lines.append("    raise ValueError(\"validation errors for UserCreate\")")
        elif "ModuleNotFoundError" in error_type:
            lines.append("    raise ModuleNotFoundError(\"No module named 'missing'\")")
        else:
            lines.append(f"    raise {error_type}(\"{error_msg}\")")
    lines.append("")
    lines.append("")

    # Main
    lines.append("def main():")
    lines.append("    mock_data = MagicMock()")

    if with_mock_data:
        lines.append("    # Load mock data from file")
        lines.append("    import json")
        lines.append("    with open(\"mock_data.json\") as f:")
        lines.append("        mock_data = json.load(f)")

    lines.append("    try:")
    lines.append("        trigger_error(mock_data)")
    lines.append("        print(\"WARNING: Error was NOT reproduced\")")
    if with_type_annotations:
        lines.append("        exit(0)  # unexpected success")
    lines.append(f"    except {error_type} as e:")
    lines.append(f'        print(f"Reproduced: {{e}}")')
    if with_type_annotations:
        lines.append("        exit(1)  # success — error reproduced")
    lines.append("")
    lines.append("")
    lines.append("if __name__ == \"__main__\":")
    lines.append("    main()")

    return "\n".join(lines)


def _build_requirements_txt(use_hallucinated_lib: bool = False) -> str:
    """Build a mock requirements.txt."""
    if use_hallucinated_lib:
        return "nonexistent-hallucinated-lib>=1.0.0\nrequests>=2.28"
    return "# No external dependencies — stdlib only\n"


def _build_mock_data_json() -> str:
    """Build a mock mock_data.json."""
    return '{\n  "key": "value",\n  "count": 42,\n  "items": []\n}\n'


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_mock_response(
    variant: str,
    trace: ParsedTrace,
    run_idx: int,
) -> dict[str, Any]:
    """Generate a mock LLM response for a given variant and trace.

    Returns:
        A dict with keys:
        - ``response_text``: the simulated LLM response text
        - ``tokens_used``: estimated token count
        - ``triggered``: whether this response would reproduce the error
        - ``hallucinated``: whether this response contains hallucinated content
    """
    profile = _QUALITY_PROFILES.get(variant, _QUALITY_PROFILES["P3_BALANCED"])
    trigger_rate, hallucination_rate, avg_chars = profile

    will_trigger = _seeded_choice(variant, trace.file, run_idx, trigger_rate)
    will_hallucinate = _seeded_choice(variant, trace.file, run_idx + 1000, hallucination_rate)

    # P1 speed: no mock_data block
    with_mock_data = variant != "P1_SPEED"
    # P4 complete: type annotations + comments
    with_type_annotations = variant == "P4_COMPLETE"
    with_few_shot_comments = variant == "P4_COMPLETE"
    # P5 security: security markers
    with_security_checks = variant == "P5_SECURITY"

    reproduce_py = _build_reproduce_py(
        trace,
        with_mock_data=with_mock_data,
        with_type_annotations=with_type_annotations,
        with_few_shot_comments=with_few_shot_comments,
        with_security_checks=with_security_checks,
        use_hallucinated_lib=will_hallucinate,
    )

    requirements = _build_requirements_txt(use_hallucinated_lib=will_hallucinate)

    # Assemble response
    blocks = [f"```reproduce.py\n{reproduce_py}\n```"]
    blocks.append(f"```requirements.txt\n{requirements}\n```")
    if with_mock_data:
        blocks.append(f"```mock_data.json\n{_build_mock_data_json()}\n```")

    response_text = "\n\n".join(blocks)

    # Add some padding text for P4/P5 to simulate verbosity
    if variant in ("P4_COMPLETE", "P5_SECURITY"):
        preamble = (
            "I've analysed the traceback and source context carefully. "
            "Here is a minimal reproduction script that triggers the original error.\n\n"
        )
        postamble = (
            "\n\n**Notes:**\n"
            "- The mock data is a placeholder; replace with actual values.\n"
            "- Run with `python reproduce.py` to verify.\n"
        )
        response_text = preamble + response_text + postamble

    # Adjust token count with some variance
    variance = _seeded_choice(variant, trace.file, run_idx + 2000, 0.5)
    char_count = len(response_text) + (100 if variance else -50)
    tokens = _estimate_tokens(max(char_count, avg_chars))

    return {
        "response_text": response_text,
        "tokens_used": tokens,
        "triggered": will_trigger,
        "hallucinated": will_hallucinate,
    }
