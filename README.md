# log2repro

<p align="center">
  <strong>Error log → runnable reproduction code generator</strong>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python 3.10+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="MIT License"></a>
  <a href="https://github.com/ChanChiChoi/log2repro/actions"><img src="https://img.shields.io/badge/tests-385-brightgreen.svg" alt="Tests"></a>
</p>

<p align="center">
  <a href="README_zh.md">中文文档</a> · <a href="docs/index.md">English Docs</a>
</p>

---

Paste a Python traceback, get a self-contained `reproduce.py` that triggers the original error — with `requirements.txt`, mock data, and a verification README.

> **45 min → 3 min** average reproduction time.

## Why log2repro?

Engineers spend 60%+ of debug time on "guess parameters, dig through databases, mock third-party APIs".

**Sentry** tells you *where* the error happened. **log2repro** gives you a *replayable scene*.

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

**Output:**

```
repro_out/
├── reproduce.py        # Minimal script that triggers the original error
├── requirements.txt    # pip dependencies
├── mock_data.json      # Test fixtures / mock data
└── README_repro.md     # Usage instructions + auto-fix history
```

**Example `reproduce.py`:**

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

## CLI Reference

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
  --extra-body TEXT    Extra JSON body for LLM API (e.g. '{"enable_thinking": false}')
  -v, --verbose        Enable verbose logging
```

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

## Evaluation

```python
from log2repro.eval_metrics import evaluate_batch, GenerationInput

batch = evaluate_batch([
    GenerationInput(trace_name="api_500", files=files, tokens_used=800, expected_error="ValueError: x"),
])
print(batch.report())
```

| Metric | Description |
|--------|-------------|
| **Runnable Rate** ↑ | Script executes without ImportError/SyntaxError |
| **Dep Conflict Rate** ↓ | requirements.txt has no version conflicts |
| **Mock Coverage** ↑ | External calls (network, DB) are properly mocked |
| **Token Efficiency** ↑ | Errors reproduced per 1,000 tokens |

## Documentation

Full documentation: **[docs/index.md](docs/index.md)**

<details>
<summary>Table of Contents</summary>

| Guide | Reference | Development |
|-------|-----------|-------------|
| [Getting Started](docs/getting-started.md) | [Parser Reference](docs/parser-reference.md) | [Architecture](docs/architecture.md) |
| [User Guide](docs/user-guide.md) | [LLM Prompt Design](docs/llm-prompt-design.md) | [Contributing](docs/contributing.md) |
| | [Evaluation Guide](docs/evaluation.md) | [Changelog](docs/changelog.md) |
| | | [Roadmap](docs/roadmap.md) |

</details>

## Development

```bash
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

<details>
<summary>Project Structure</summary>

```
log2repro/
├── src/log2repro/
│   ├── cli.py              # Typer CLI entry point
│   ├── eval_metrics.py     # 4 quality metrics
│   ├── parsers/            # Log parsing (traceback, sentry, CI)
│   ├── extractors/         # AST context extraction
│   ├── generators/         # LLM generation + prompts
│   ├── validators/         # Sandbox + auto-fix
│   └── utils/              # I/O helpers
├── tests/                  # 385 tests, 30+ fixtures
└── benchmarks/             # Prompt variant benchmarking
```

</details>

## Acknowledgements

- [litellm](https://github.com/BerriAI/litellm) — unified LLM API
- [Typer](https://github.com/tiangolo/typer) — CLI framework
- [Rich](https://github.com/Textualize/rich) — terminal formatting
- [Pydantic](https://github.com/pydantic/pydantic) — data validation

## License

[MIT](LICENSE)
