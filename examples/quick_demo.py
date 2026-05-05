#!/usr/bin/env python3
"""Quick demo: paste a traceback, get structured context.

Usage:
    python examples/quick_demo.py
    python examples/quick_demo.py path/to/error.log
    cat error.log | python examples/quick_demo.py -
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running from project root without installing
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from log2repro.parsers.stacktrace import StacktraceParser
from log2repro.extractors.ast_parser import extract_ast_context_from_source

# A sample traceback for demo purposes
SAMPLE_TRACEBACK = """\
Traceback (most recent call last):
  File "/app/services/user_service.py", line 87, in get_user_profile
    user = self.cache[user_id]
  File "/app/services/user_service.py", line 45, in __getitem__
    return self._store[key]
KeyError: 'usr_2938471'
"""


def main() -> None:
    """Run the demo pipeline."""
    # 1. Get input
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "-":
            raw = sys.stdin.read()
        elif Path(arg).exists():
            raw = Path(arg).read_text()
        else:
            raw = arg
    else:
        print("No input provided. Using built-in sample traceback.\n")
        raw = SAMPLE_TRACEBACK

    print("=" * 60)
    print("INPUT TRACEBACK")
    print("=" * 60)
    print(raw.strip())
    print()

    # 2. Parse
    parser = StacktraceParser()
    traces = parser.parse(raw)

    if not traces:
        print("ERROR: Could not parse any trace from input.")
        sys.exit(1)

    trace = traces[0]

    print("=" * 60)
    print("PARSED RESULT")
    print("=" * 60)
    print(json.dumps(trace.to_context_dict(), indent=2))
    print()

    # 3. AST context (best-effort, won't work for /app/ paths)
    print("=" * 60)
    print("AST CONTEXT (if source file accessible)")
    print("=" * 60)
    source_path = Path(trace.file)
    if source_path.exists():
        ctx = extract_ast_context_from_source(
            source_path.read_text(),
            filename=trace.file,
            target_line=trace.line,
        )
        print(json.dumps(ctx.to_context_dict(), indent=2))
    else:
        print(f"Source file not accessible: {trace.file}")
        print("(This is expected for remote/container paths)")
    print()

    # 4. Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Error:    {trace.error}")
    print(f"  File:     {trace.file}:{trace.line}")
    print(f"  Chain:    {len(trace.chain)} frames")
    print(f"  Vars:     {', '.join(trace.context_vars) or '(none)'}")
    print()
    print("Next steps (D2): pipe this context into LLM to generate reproduce.py")


if __name__ == "__main__":
    main()
