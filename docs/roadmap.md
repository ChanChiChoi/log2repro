# Roadmap

## Milestones

### D1 — Core Parsing & AST Extraction ✅

- [x] `ParsedTrace` model + `BaseParser` ABC
- [x] Python traceback regex parser
- [x] Chained exception support
- [x] AST context extraction (signatures, imports, vars)
- [x] Typer CLI entry point
- [x] Dry-run mode

### D2 — LLM Generation & Sandbox Feedback ✅

- [x] `litellm` integration (isolated `_call_llm()`)
- [x] 3 system prompts (general/network/database)
- [x] Jinja2 user message template
- [x] Markdown code block parsing
- [x] Sandbox feedback loop (generate → verify → refine)

### D3 — Sandbox Execution & Auto-Fix ✅

- [x] `venv` + `subprocess` sandbox
- [x] Network isolation via env vars
- [x] Error classification (7 fixable types)
- [x] Auto-fix chain (3 rounds)
- [x] Graceful degradation with suggestions
- [x] CLI integration (`--sandbox-timeout`, `--max-refine`, `--output-dir`)
- [x] README_repro.md generation

### D4 — Quality Evaluation ✅

- [x] Code runnable rate metric
- [x] Dependency conflict rate metric
- [x] Mock coverage rate metric
- [x] Token efficiency metric
- [x] Batch evaluation + Markdown report

### D5 — Advanced Parsers ✅

- [x] Sentry JSON parser
- [x] CI log parser (ANSI stripping)
- [x] Auto-detection in CLI

### D6 — Benchmark Framework ✅

- [x] 5 prompt variants (P1-P5)
- [x] Benchmark runner
- [x] Hallucination + trigger validation
- [x] Per-trace breakdown
- [x] Deterministic mock responses

### D7 — Documentation & Polish ✅

- [x] README.md for GitHub
- [x] CODE_LOGIC.md (full code logic doc)
- [x] docs/ directory (9 files)
  - [x] getting-started.md
  - [x] architecture.md
  - [x] user-guide.md
  - [x] parser-reference.md
  - [x] llm-prompt-design.md
  - [x] evaluation.md
  - [x] contributing.md
  - [x] changelog.md
  - [x] roadmap.md

---

### D8 — Root Cause Analysis & Fix Recommendations (Planned)

- [ ] `--analyze` CLI flag to enable root cause analysis mode
- [ ] LLM prompt for error cause analysis (structured output: cause → impact → fix)
- [ ] `analysis.md` output with root cause, affected code path, and fix recommendations
- [ ] Fix suggestions ranked by confidence (high/medium/low)
- [ ] Integration with reproduction: analysis + repro in one pipeline
- [ ] Python API `analyze(traceback)` for programmatic use
- [ ] Unit tests for analysis output structure and content quality

### D9 — Language Expansion (Planned)

- [ ] JavaScript/Typetrace parser
- [ ] Java stack trace parser
- [ ] Go panic parser
- [ ] Rust panic parser
- [ ] Language-specific system prompts

### D10 — Web UI (Planned)

- [ ] FastAPI backend
- [ ] React frontend
- [ ] Paste-to-reproduce web interface
- [ ] History / saved reproductions
- [ ] Shareable repro links

### D11 — CI/CD Integration (Planned)

- [ ] GitHub Action
- [ ] GitLab CI template
- [ ] Auto-comment on issues with repro script
- [ ] Sentry plugin / webhook

### D12 — Advanced Features (Planned)

- [ ] Multi-file reproduction (not just single script)
- [ ] Docker-based sandbox (stronger isolation)
- [ ] Custom prompt templates (user-defined)
- [ ] Reproduction diff (before/after fix)
- [ ] Cost tracking per generation

---

## Design Principles

1. **LLM-agnostic** — Never lock to a single provider
2. **AST over hallucination** — Hard constraints from real code
3. **Sandbox before output** — Verify before delivering
4. **Graceful degradation** — Always give actionable output
5. **Zero invasion** — Paste text, no SDK required
