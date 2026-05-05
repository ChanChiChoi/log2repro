# Architecture

## System Overview

log2repro converts error logs into runnable reproduction scripts through a 5-stage pipeline:

```
┌──────────┐    ┌──────────────┐    ┌──────────────┐    ┌───────────────┐    ┌──────────┐
│  Stage 1 │    │   Stage 2    │    │   Stage 3    │    │    Stage 4    │    │  Stage 5 │
│  Parse   │───▶│  AST Extract │───▶│  LLM Generate│───▶│ Sandbox + Fix │───▶│  Output  │
│  (regex) │    │  (ast module)│    │  (litellm)   │    │ (venv+subproc)│    │ (4 files)│
└──────────┘    └──────────────┘    └──────────────┘    └───────────────┘    └──────────┘
```

## Module Map

```
src/log2repro/
├── cli.py              # Entry point + pipeline orchestration
├── eval_metrics.py     # Quality evaluation (4 metrics)
├── parsers/
│   ├── base.py         # ParsedTrace model + BaseParser ABC
│   ├── stacktrace.py   # Python traceback parser (regex)
│   ├── sentry.py       # Sentry JSON parser
│   └── ci_log.py       # CI log parser (ANSI stripping)
├── extractors/
│   └── ast_parser.py   # AST context extraction
├── generators/
│   ├── prompts.py      # System prompts + Jinja2 templates
│   └── code_gen.py     # LLM generation + sandbox feedback
├── validators/
│   ├── sandbox.py      # venv + subprocess execution
│   └── auto_fix.py     # Auto-fix chain (classify → repair → degrade)
└── utils/
    └── io.py           # Input reading (file/stdin/raw)
```

## Design Decisions

### 1. Isolated LLM entry point

`_call_llm()` in `code_gen.py` is the **only** function that touches `litellm`. This makes the entire generation pipeline mockable for testing without needing a real LLM.

### 2. Regex over grammar for parsing

Python tracebacks have a well-defined but informal format. Regex is simpler and faster than a full parser, and handles the majority of real-world tracebacks. Edge cases (exotic formatting, deeply nested chains) are handled by multiple regex patterns and backward-scanning heuristics.

### 3. AST for context, LLM for code

AST extraction provides **hard constraints** (real variable names, actual imports, function signatures) that prevent the LLM from hallucinating non-existent libraries or variables. The LLM handles the creative part (constructing mocks, assembling the script).

### 4. Sandbox before output

Every generated script runs in an isolated venv with network disabled before being returned to the user. This catches:
- Import errors (missing dependencies)
- Syntax errors
- Runtime errors that aren't the target error

### 5. Graceful degradation

If the auto-fix loop fails after 3 rounds, the system outputs human-readable repair suggestions instead of silently failing. This ensures the user always gets actionable output.

### 6. Network isolation via env vars

Rather than OS-level firewall or Docker, network isolation uses environment variables (`NO_PROXY=*`, empty proxy vars). This is portable, testable, and sufficient for preventing accidental real API calls from `requests`/`httpx`/`urllib`.

## Data Flow

### Stage 1: Parse

**Input:** Raw text (file, stdin, or string)

**Output:** `list[ParsedTrace]`

- `StacktraceParser` splits on `Traceback (most recent call last):`
- Handles chained exceptions (`During handling...`)
- Extracts: file, line, error type+message, call chain, context variables

### Stage 2: AST Extract

**Input:** `ParsedTrace` (provides file path, line number, function name from chain)

**Output:** `ASTContext`

- Reads the source file (if accessible)
- Uses Python `ast` module to extract:
  - Function signature (with type annotations and defaults)
  - Import statements
  - Annotated variables (global + local)
- Falls back gracefully if file doesn't exist or can't be parsed

### Stage 3: LLM Generate

**Input:** `ReproContext` (trace + AST + model)

**Output:** `dict[str, str]` (filename → content)

1. `select_system_prompt()` picks the right system prompt (general/network/database)
2. `render_user_message()` renders Jinja2 template with all context
3. `_call_llm()` calls the LLM
4. `parse_llm_response()` extracts fenced code blocks
5. `_validate_files()` checks all 3 required files are present
6. On failure: retry up to 2 times with exponential backoff

### Stage 4: Sandbox + Fix

**Input:** Generated files + original error

**Output:** Verified/fixed files

1. `run_in_sandbox()`:
   - Creates temporary venv
   - Runs `pip install -r requirements.txt`
   - Executes `reproduce.py` with network isolation
   - Checks if original error appears in stderr

2. If not reproduced, feeds stderr back to LLM for refinement (up to 2 rounds)

3. `auto_fix_loop()`:
   - Classifies the error (SyntaxError, ImportError, etc.)
   - If fixable: targeted LLM repair (up to 3 rounds)
   - If not fixable: returns with suggestions
   - If exhausted: degrades to dry-run with suggestions

### Stage 5: Output

**Input:** Final files + trace info

**Output:** 4 files in output directory

| File | Content |
|------|---------|
| `reproduce.py` | Minimal reproduction script |
| `requirements.txt` | pip dependencies |
| `mock_data.json` | Test fixtures / mock data |
| `README_repro.md` | Usage instructions + fix history |

## Dependency Graph

```
cli.py
├── parsers/stacktrace.py ──▶ parsers/base.py
├── extractors/ast_parser.py
├── generators/code_gen.py
│   ├── generators/prompts.py
│   ├── parsers/base.py
│   └── validators/sandbox.py
├── validators/auto_fix.py
│   ├── generators/code_gen.py
│   ├── generators/prompts.py
│   └── validators/sandbox.py
├── validators/sandbox.py
├── eval_metrics.py
│   ├── generators/code_gen.py
│   └── validators/sandbox.py
└── utils/io.py
```

## Testing Strategy

- **Unit tests:** Each module has its own test file with isolated tests
- **Mock LLM:** All LLM calls go through `_call_llm()`, easily mocked
- **Real subprocess:** Sandbox tests run actual Python scripts in venvs
- **Fixture traces:** 30+ real-world error traces covering edge cases
- **Benchmark framework:** 5 prompt variants × 5 traces × N runs
