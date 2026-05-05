# log2repro

**Error log → runnable reproduction code generator.**

> **[中文文档](docs_zh/)** | **[English Docs](docs/)**

Paste a Python traceback, get a self-contained `reproduce.py` that triggers the original error — with `requirements.txt`, mock data, and a verification README.

> Average reproduction time: **45 min → 3 min**.

## Why?

Engineers spend 60%+ of debug time on "guess parameters, dig through databases, mock third-party APIs". Sentry tells you *where* the error happened; log2repro gives you a *replayable scene*.

| | Sentry | log2repro |
|---|---|---|
| **Output** | Stack trace, breadcrumbs, user context | `reproduce.py` + `requirements.txt` + mock data |
| **Integration** | Requires SDK / code changes | Zero-invasion: paste text, CI log, or file |
| **Solves** | Monitor → discover → locate | Locate → construct env → verify fix |

## Features

- **AST-powered context extraction** — extracts real variable names, function signatures, and imports from source code to constrain LLM output (no hallucinated libraries)
- **Sandbox verification** — runs generated code in an isolated venv with network disabled, verifies the original error is actually reproduced
- **Auto-fix loop** — if the script fails (SyntaxError, ModuleNotFoundError, etc.), feeds the error back to the LLM for targeted repair (up to 3 rounds)
- **Graceful degradation** — after 3 failed fixes, outputs human-readable repair suggestions instead of silently failing
- **Multi-format support** — Python tracebacks, chained exceptions, async errors, C extension errors, dynamic imports
- **LLM-agnostic** — uses [litellm](https://github.com/BerriAI/litellm), supports OpenAI, Anthropic, local models, etc.

## Installation

```bash
# With uv (recommended)
uv pip install log2repro

# With pip
pip install log2repro

# From source
git clone https://github.com/ChanChiChoi/log2repro.git
cd log2repro
uv sync
```

## Quick Start

```bash
# Full pipeline: parse → generate → sandbox → auto-fix → output
log2repro run error.log --output-dir ./repro_out

# From stdin
cat error.log | log2repro run - --output-dir ./repro_out

# Paste directly
log2repro run 'Traceback (most recent call last):
  File "app.py", line 10, in process
    result = api.fetch(user_id)
requests.exceptions.ConnectionError: Connection refused'

# Parse only (no LLM calls)
log2repro run error.log --dry-run
```

### Output

```
repro_out/
├── reproduce.py        # Minimal script that triggers the original error
├── requirements.txt    # pip dependencies
├── mock_data.json      # Test fixtures / mock data
└── README_repro.md     # Usage instructions + auto-fix history
```

### Example `reproduce.py`

```python
"""Minimal reproduction for ConnectionError."""
from unittest.mock import patch, MagicMock

def test_api_connection():
    with patch("requests.get") as mock_get:
        mock_get.side_effect = ConnectionError("Connection refused")
        import requests
        requests.get("http://api/users/123")  # raises ConnectionError

if __name__ == "__main__":
    test_api_connection()
```

## Usage

```bash
log2repro run <input> [OPTIONS]

Arguments:
  input                File path, "-" for stdin, or raw traceback text

Options:
  -m, --model TEXT     LLM model (default: gpt-4o)
  -n, --dry-run        Parse only, skip LLM generation
  -d, --output-dir     Output directory (default: ./repro_out)
  -o, --output         Write JSON to file (legacy mode)
  --sandbox-timeout    Max seconds for sandbox execution (default: 10)
  --max-refine         Max sandbox→LLM refinement rounds (default: 2)
  -v, --verbose        Enable verbose logging
```

## How It Works

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌───────────────┐
│  Parse Log  │────▶│  AST Extract │────▶│  LLM Generate│────▶│ Sandbox Verify│
│  (regex)    │     │  (ast module)│     │  (litellm)   │     │  (venv+subproc)│
└─────────────┘     └──────────────┘     └──────────────┘     └───────┬───────┘
                                                                      │
                                                    ┌─────────────────┼─────────────────┐
                                                    │ reproduced?     │ fixable error?   │
                                                    ▼                 ▼                  ▼
                                                ✅ Done          LLM Fix (×3)      Degraded +
                                                                          │         Suggestions
                                                                          ▼
                                                                    Re-sandbox
```

1. **Parse** — regex-based parser extracts file, line, error type, call chain from traceback
2. **AST Extract** — Python `ast` module pulls real variable names, function signatures, imports from source
3. **LLM Generate** — sends structured prompt (error + AST context) to LLM, parses Markdown code blocks
4. **Sandbox Verify** — creates venv, installs deps, runs script with network disabled, checks if original error appears in stderr
5. **Auto-fix** — if sandbox fails with a fixable error (SyntaxError, ImportError, etc.), feeds stderr back to LLM for targeted repair

## Supported Error Formats

| Category | Examples |
|----------|---------|
| Python tracebacks | `ValueError`, `KeyError`, `TypeError`, `AttributeError` |
| Chained exceptions | `During handling of the above exception...` |
| Async errors | `TaskGroup`, `asyncio.TimeoutError`, async generators |
| C extensions | `numpy._UFuncNoLoopError`, `sqlite3.OperationalError`, `struct.error` |
| Dynamic imports | `importlib`, `__import__`, lazy imports, module reload |
| Deep call stacks | Decorators, middleware, recursion, context managers, callbacks |
| Network/DB | `requests`, `httpx`, `aiohttp`, `sqlalchemy`, `psycopg2` |

## Evaluation Metrics

```python
from log2repro.eval_metrics import evaluate_batch, GenerationInput

batch = evaluate_batch([
    GenerationInput(trace_name="api_500", files=files, tokens_used=800, expected_error="ValueError: x"),
])
print(batch.report())
```

| Metric | Description |
|--------|-------------|
| **代码可运行率** ↑ | Script executes without ImportError/SyntaxError |
| **依赖冲突率** ↓ | requirements.txt has no version conflicts |
| **Mock 覆盖率** ↑ | External calls (network, DB) are properly mocked |
| **Token 效率** ↑ | Errors reproduced per 1,000 tokens |

## Development

```bash
# Setup
git clone https://github.com/ChanChiChoi/log2repro.git
cd log2repro
uv sync --group dev

# Run tests (385 tests, ~2.5 min)
uv run pytest -v

# Run benchmarks
uv run python -m benchmarks.runner

# Lint
uv run ruff check src/ tests/
```

### Project Structure

```
log2repro/
├── src/log2repro/
│   ├── cli.py              # Typer CLI entry point
│   ├── eval_metrics.py     # 4 quality metrics (runnable, deps, mock, tokens)
│   ├── parsers/
│   │   ├── base.py         # ParsedTrace model + BaseParser ABC
│   │   ├── stacktrace.py   # Python traceback parser (regex)
│   │   ├── sentry.py       # Sentry JSON parser (stub)
│   │   └── ci_log.py       # CI log parser (stub)
│   ├── extractors/
│   │   └── ast_parser.py   # AST context extraction (signatures, imports, vars)
│   ├── generators/
│   │   ├── prompts.py      # System prompts (general/network/database) + templates
│   │   └── code_gen.py     # LLM generation + sandbox feedback loop
│   ├── validators/
│   │   ├── sandbox.py      # venv + subprocess sandbox with network isolation
│   │   └── auto_fix.py     # Auto-fix chain (classify → LLM repair → degrade)
│   └── utils/
│       └── io.py           # Input reading (file/stdin/raw string)
├── tests/
│   ├── fixtures/            # 30+ real-world error trace samples
│   └── test_*.py            # 385 tests
└── benchmarks/
    ├── prompt_variants.py   # 5 prompt variants for comparison
    ├── runner.py            # Benchmark execution engine
    └── validator.py         # Hallucination + trigger detection
```

## Acknowledgements

- [litellm](https://github.com/BerriAI/litellm) — unified LLM API
- [Typer](https://github.com/tiangolo/typer) — CLI framework
- [Rich](https://github.com/Textualize/rich) — terminal formatting
- [Pydantic](https://github.com/pydantic/pydantic) — data validation

## License

MIT
