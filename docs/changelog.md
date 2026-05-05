# Changelog

## [Unreleased]

### D7 — Documentation & Polish

- Added comprehensive docs under `docs/` (9 files)
- Generated `CODE_LOGIC.md` with full module-by-module logic documentation
- Added `README.md` for GitHub

### D6 — Benchmark Framework

- `benchmarks/prompt_variants.py` — 5 prompt variants (P1-P5)
- `benchmarks/runner.py` — Benchmark execution engine
- `benchmarks/validator.py` — Hallucination + trigger detection
- `benchmarks/report.py` — Markdown report generation
- `benchmarks/mock_responses.py` — Deterministic mock responses

### D5 — Advanced Parsers

- `parsers/sentry.py` — Sentry JSON parser (full implementation)
- `parsers/ci_log.py` — CI log parser with ANSI stripping
- Multi-format auto-detection in CLI

### D4 — Quality Evaluation

- `eval_metrics.py` — 4 quality metrics
  - Code runnable rate (代码可运行率)
  - Dependency conflict rate (依赖冲突率)
  - Mock coverage rate (Mock 覆盖率)
  - Token efficiency (Token 效率)
- `GenerationInput`, `SingleEvalResult`, `BatchEvalResult` data models
- `BatchEvalResult.report()` — Markdown table output

### D3 — Sandbox Execution & Auto-Fix

- `validators/sandbox.py` — Full sandbox implementation
  - `venv` creation with pip
  - `subprocess.run()` with timeout
  - Network isolation via environment variables
  - `SandboxResult` dataclass
- `validators/auto_fix.py` — Auto-fix chain
  - Error classification (7 fixable types)
  - Targeted LLM repair prompts
  - 3-round fix loop with graceful degradation
  - `FixResult` dataclass
- CLI integration: `--sandbox-timeout`, `--max-refine`, `--output-dir`, `--verbose`
- `_generate_readme()` — README_repro.md with fix history and suggestions

### D2 — LLM Generation & Sandbox Feedback

- `generators/code_gen.py` — LLM generation pipeline
  - `_call_llm()` — Isolated litellm entry point
  - `generate_repro_script()` — Full pipeline with sandbox feedback
  - `parse_llm_response()` — Markdown code block extraction
  - Exponential backoff retry
- `generators/prompts.py` — System prompts + Jinja2 templates
  - 3 system prompts (general/network/database)
  - `select_system_prompt()` — Auto-selection by error type
  - `REFINE_PROMPT_TEMPLATE` — Sandbox feedback refinement
- Sandbox feedback loop: generate → verify → refine (up to N rounds)

### D1 — Core Parsing & AST Extraction

- `parsers/base.py` — `ParsedTrace` model, `BaseParser` ABC
- `parsers/stacktrace.py` — Python traceback parser
  - Regex-based parsing with `re.MULTILINE`
  - Chained exception support
  - Context variable extraction
- `extractors/ast_parser.py` — AST context extraction
  - Function signature extraction (with types + defaults)
  - Import statement extraction
  - Variable annotation extraction
- `cli.py` — Typer CLI entry point
  - `log2repro run` command
  - `log2repro version` command
  - Dry-run mode
- `utils/io.py` — Input reading (file/stdin/raw)

## Version History

| Version | Date | Milestone | Tests |
|---------|------|-----------|-------|
| 0.1.0 | D1 | Core parsing + AST | ~80 |
| 0.2.0 | D2 | LLM generation + feedback | ~150 |
| 0.3.0 | D3 | Sandbox + auto-fix | ~300 |
| 0.4.0 | D4 | Evaluation metrics | ~350 |
| 0.5.0 | D5 | Advanced parsers | ~370 |
| 0.6.0 | D6 | Benchmarks | ~385 |
| 0.7.0 | D7 | Documentation | ~385 |
