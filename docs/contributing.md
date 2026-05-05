# Contributing

## Development Setup

```bash
# Clone
git clone https://github.com/ChanChiChoi/log2repro.git
cd log2repro

# Install with dev dependencies
uv sync --group dev

# Verify setup
uv run pytest --co -q  # list tests without running
```

## Project Layout

```
src/log2repro/          # Main package
├── cli.py              # CLI entry point
├── eval_metrics.py     # Quality metrics
├── parsers/            # Log parsing
├── extractors/         # AST extraction
├── generators/         # LLM generation
├── validators/         # Sandbox + auto-fix
└── utils/              # I/O helpers

tests/                  # Test suite
├── fixtures/           # 30+ error trace samples
└── test_*.py           # Test modules

benchmarks/             # Benchmark framework
```

## Running Tests

```bash
# All tests (385 tests, ~2.5 min)
uv run pytest -v

# Specific module
uv run pytest tests/test_sandbox.py -v

# With coverage
uv run pytest --cov=log2repro --cov-report=term-missing

# Stop on first failure
uv run pytest -x
```

## Code Style

- **Formatter/Linter:** Ruff
- **Line length:** 88 characters (Black-compatible)
- **Type hints:** Required for public functions
- **Docstrings:** Google style for public APIs

```bash
# Lint
uv run ruff check src/ tests/

# Format
uv run ruff format src/ tests/
```

## Adding a New Parser

1. Create `src/log2repro/parsers/my_parser.py`
2. Implement `BaseParser` interface:

```python
from log2repro.parsers.base import BaseParser, ParsedTrace

class MyParser(BaseParser):
    def can_parse(self, text: str) -> bool:
        # Return True if this parser handles the input
        ...

    def parse(self, text: str) -> list[ParsedTrace]:
        # Parse text and return traces
        ...
```

3. Add tests in `tests/test_my_parser.py`
4. Add fixture traces in `tests/fixtures/`
5. Register in `cli.py` parser chain

## Adding a New Metric

1. Add function to `src/log2repro/eval_metrics.py`
2. Integrate into `evaluate_single()`
3. Add tests in `tests/test_eval_metrics.py`
4. Update `BatchEvalResult.report()` if needed

## Modifying Prompts

1. Edit `src/log2repro/generators/prompts.py`
2. Run benchmarks to compare:

```bash
uv run python -m benchmarks.runner
```

3. Update `CODE_LOGIC.md` section 6.1

## Test Fixtures

Add real-world error traces to `tests/fixtures/`:

```
tests/fixtures/
├── connection_error.txt
├── sqlalchemy_not_found.txt
├── chained_exception.txt
├── sentry_payload.json
└── ci_log_ansi.txt
```

Each fixture should be a minimal, self-contained error trace.

## Mocking LLM Calls

All LLM calls go through `_call_llm()` in `code_gen.py`. Mock it in tests:

```python
from unittest.mock import patch

def test_my_feature():
    mock_response = "```python\nprint('hello')\n```"
    with patch("log2repro.generators.code_gen._call_llm", return_value=mock_response):
        # Your test code
        ...
```

## Sandbox Tests

Sandbox tests run real Python scripts in venvs. They are slower but test actual behavior:

```python
def test_sandbox_execution():
    result = run_in_sandbox(
        script_path=Path("test_script.py"),
        timeout=10,
        expected_error="ValueError: test",
    )
    assert result.error_reproduced
```

## Pull Request Process

1. Create a feature branch from `main`
2. Write code + tests
3. Run full test suite: `uv run pytest -v`
4. Run linter: `uv run ruff check src/ tests/`
5. Update `CODE_LOGIC.md` if changing module logic
6. Submit PR with clear description

## Commit Messages

Follow conventional commits:

```
feat: add Sentry JSON parser
fix: handle underscore-prefixed exception types
docs: update CODE_LOGIC.md for sandbox changes
test: add edge case for chained exceptions
refactor: extract _call_llm for testability
```

## Documentation

When modifying code, update these docs as needed:

| Change | Update |
|--------|--------|
| New module | `CODE_LOGIC.md` + `docs/architecture.md` |
| New CLI flag | `docs/user-guide.md` + `CODE_LOGIC.md` §9 |
| New metric | `docs/evaluation.md` + `CODE_LOGIC.md` §8 |
| New parser | `docs/parser-reference.md` + `CODE_LOGIC.md` §4 |
| Prompt change | `docs/llm-prompt-design.md` + `CODE_LOGIC.md` §6 |
