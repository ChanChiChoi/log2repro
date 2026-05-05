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

### D9 — Python Error Format Completeness (Planned)

> Detailed reference: [python-error-format-gaps.md](python-error-format-gaps.md)

- [ ] SyntaxError / IndentationError / TabError with `^` caret indicator
  - Standalone: 0 traces (no call sites matched)
  - With prior stack: points to wrong frame (last `in func` frame, not SyntaxError line)
  - Support `File "x.py", line N` format (without `, in func_name`)
  - Extract error column from caret position
- [ ] ExceptionGroup / BaseExceptionGroup (Python 3.11+)
  - `+ Exception Group Traceback` header not matched by `^Traceback` regex
  - `|`-prefixed lines block `_RE_CALL_SITE` matching for sub-exceptions
  - Parse sub-exceptions recursively, extract all as separate ParsedTrace objects
- [ ] Logging exc_info prefix format (high priority)
  - `2024-01-15 ERROR ... Traceback (most recent call last):` — timestamp prefix prevents `^Traceback` matching
  - Most common format in production logs (`logging.exception()`, `logging.error(exc_info=True)`)
- [ ] Warning format (`file:line: WarningType: message`)
  - Add `WarningParser` for non-traceback warning output
- [ ] RecursionError depth preservation
  - Parse `[Previous line repeated N more times]` line
  - Store repetition count in ParsedTrace metadata
- [ ] Exception notes (Python 3.11+ `add_note()`)
  - Capture note lines after the exception line
  - Add `notes: list[str]` field to ParsedTrace
- [ ] Re-raise annotation (`raise` without arguments)
  - Bare `raise` currently parsed as normal traceback
  - Should annotate ParsedTrace as re-raise for better reproduction context
- [ ] Update `_RE_CALL_SITE` to optionally match `File "x.py", line N` without `in func`

### D10 — LLM / Agent / MCP Error Format Support (Planned)

> Detailed reference: [python-error-format-gaps.md § LLM/Agent/MCP](python-error-format-gaps.md#10-llm-api-error-json-response)

- [ ] LLM API Error JSON parser (`APIErrorParser`)
  - Parse OpenAI / Anthropic / LiteLLM JSON error responses
  - Extract `error.type`, `error.code`, `error.message` → `ParsedTrace`
- [ ] Token / Context Window error parser (`LLMErrorParser`)
  - Parse plain-text context limit and rate limit messages
  - Extract model name, token counts, retry-after
- [ ] MCP JSON-RPC error parser (`MCPRpcParser`)
  - Parse `{"jsonrpc":"2.0","error":{"code":...,"message":...}}` from MCP stderr
  - Map JSON-RPC error codes to human-readable types
- [ ] LangChain Agent verbose output parser (`AgentLogParser`)
  - Parse `Thought/Action/Observation` chain format
  - Extract tool name, args, error from `Observation` lines
- [ ] Agent tool execution error (truncated format)
  - Handle `[AgentError] Tool execution failed:` style output
- [ ] Google Gemini API error parser (`GeminiErrorParser`)
  - Parse `google.api_core.exceptions` (BadRequest, ResourceExhausted, PermissionDenied)
  - Handle `google-genai` SDK's `ClientError`/`ServerError` format
- [ ] A2A protocol error parser (`A2AErrorParser`)
  - Parse Agent-to-Agent JSON-RPC 2.0 errors
  - Map A2A-specific codes: -32001 Task not found, -32002 Task cannot be canceled, -32003 Push notification not supported, -32004 Unsupported operation, -32005 Content type not supported
- [ ] Content moderation / safety filter errors
  - Parse `content_policy_violation` (OpenAI), safety-related `invalid_request_error` (Anthropic)
  - Extract violation categories for reproduction context
- [ ] Tool calling / function calling errors
  - Parse JSON Schema validation failures (`strict: true` unsupported fields: `format`, `allOf`, `anyOf`)
  - Parse tool parameter type mismatch errors
  - Parse `run_requires_action` / tool output formatting errors (OpenAI Assistants API)
- [ ] OpenAI Responses API errors
  - Parse `response.failed` SSE events: `{"type":"response.failed","response":{"error":{...}}}`
  - Handle the new API format alongside Chat Completions
- [ ] Agent framework errors (CrewAI / AutoGen / Google ADK / Semantic Kernel)
  - Parse CrewAI `CrewError` / `AgentExecutionError` wrapper format
  - Parse AutoGen `TerminationException` / `GroupChatError` format
  - Parse Google ADK `google.adk.errors` format
- [ ] LiteLLM unified exception system
  - Parse 8 exception classes: `AuthenticationError`, `RateLimitError`, `ContextWindowExceededError`, `BudgetExceededError`, `ContentPolicyViolationError`, etc.
  - Map LiteLLM proxy unified JSON error format
- [ ] Anthropic Extended Thinking errors
  - Parse thinking block format errors and `budget_tokens` exceeded errors
- [ ] Embedding API errors
  - Parse OpenAI/Anthropic embedding endpoint errors (dimension mismatch, input too long)
  - Extend `APIErrorParser` for embedding-specific error codes
- [ ] Batch API errors
  - Parse OpenAI Batch API `batch.failed` status with error line count
  - Extend `APIErrorParser` for batch-specific error format
- [ ] Realtime API WebSocket errors
  - Parse OpenAI Realtime API WebSocket error events
  - Handle connection-level and session-level error types
- [ ] Audio API errors (Whisper / TTS / Realtime Voice)
  - Parse OpenAI Whisper transcription errors (unsupported codec, file size, duration limits)
  - Parse TTS errors (invalid voice/model, input text too long)
  - Parse Realtime Voice API audio streaming errors
- [ ] Document / PDF input errors
  - Parse Anthropic PDF errors (`document` content block, base64 encoding, size ~10MB limit)
  - Parse Google Gemini file upload errors (`client.files.upload()`, MIME type)
  - Parse OpenAI Assistants API file upload errors
- [ ] Google Gemini multi-modal errors
  - Parse video upload/processing errors (format, size, duration)
  - Parse audio input errors
  - Parse File API errors (`client.files.upload()`)
  - Handle multi-modal token counting differences
- [ ] Image generation API errors (DALL-E / Imagen)
  - Parse content policy violations specific to generation
  - Parse invalid generation parameters (size, quality, style, prompt length)
  - Parse generation-specific rate limits
- [ ] Video understanding errors
  - Parse Gemini video upload/processing errors
  - Parse video duration and format limits
- [ ] Multi-modal token counting errors
  - Parse resolution-based image token errors (OpenAI)
  - Parse per-media-type token cost errors (Gemini)
  - Parse mixed-media context window calculation errors
- [ ] LLM-aware system prompts
  - New `SYSTEM_PROMPT_LLM` for LLM/Agent errors (mock API responses, retry logic)
  - Auto-select when error type matches `openai.*`, `anthropic.*`, `litellm.*`, `langchain.*`, `google.*`, `crewai.*`

### D11 — Language Expansion (Planned)

- [ ] JavaScript/Typetrace parser
- [ ] Java stack trace parser
- [ ] Go panic parser
- [ ] Rust panic parser
- [ ] Language-specific system prompts

### D12 — Web UI (Planned)

- [ ] FastAPI backend
- [ ] React frontend
- [ ] Paste-to-reproduce web interface
- [ ] History / saved reproductions
- [ ] Shareable repro links

### D13 — CI/CD Integration (Planned)

- [ ] GitHub Action
- [ ] GitLab CI template
- [ ] Auto-comment on issues with repro script
- [ ] Sentry plugin / webhook

### D14 — Advanced Features (Planned)

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
