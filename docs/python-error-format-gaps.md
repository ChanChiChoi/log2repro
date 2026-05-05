# Python Error Format Gaps — Detailed Reference

> This document provides detailed information on Python error formats that log2repro does **not** yet support. Each section includes real-world examples, root cause analysis, and implementation notes. Referenced by [Roadmap D9](roadmap.md).

---

## 1. SyntaxError / IndentationError / TabError with `^` Caret

### Real-World Format

Python's `SyntaxError` has a unique traceback format that differs from all other exceptions. Instead of showing `File "x.py", line N, in func_name`, it shows:

```
Traceback (most recent call last):
  File "app.py", line 3
    x = 1 +
           ^
SyntaxError: invalid syntax
```

With a prior call stack:

```
Traceback (most recent call last):
  File "main.py", line 10, in run
    exec(code)
  File "<string>", line 3
    x = 1 +
           ^
SyntaxError: invalid syntax
```

`IndentationError` and `TabError` follow the same format:

```
Traceback (most recent call last):
  File "app.py", line 5
    return x
    ^
IndentationError: unexpected indent
```

```
Traceback (most recent call last):
  File "app.py", line 3
    	x = 1
        ^
TabError: inconsistent use of tabs and spaces in indentation
```

### Why It Fails

The `_RE_CALL_SITE` regex requires `, in func_name`:

```python
_RE_CALL_SITE = re.compile(
    r'^\s*File "(?P<file>[^"]+)",\s*line\s+(?P<line>\d+),\s*in\s+(?P<func>\S+)',
    re.MULTILINE,
)
```

SyntaxError lines like `File "app.py", line 3` (no `, in func`) are never matched. When no call sites are found, `_parse_single_block()` returns `None`.

### Current Behavior (Verified)

| Scenario | Result |
|----------|--------|
| Standalone SyntaxError | 0 traces parsed (silent failure) |
| SyntaxError with prior call stack | Parses the prior stack but **points to wrong frame** — last `in func` frame (e.g. `main.py:10`) instead of the SyntaxError line (`<string>:3`) |
| `IndentationError` | 0 traces parsed (same failure) |
| `TabError` | 0 traces parsed (same failure) |

### What Needs to Change

1. **Add a new regex** for the SyntaxError call-site format:
   ```python
   _RE_CALL_SITE_NO_FUNC = re.compile(
       r'^\s*File "(?P<file>[^"]+)",\s*line\s+(?P<line>\d+)\s*$',
       re.MULTILINE,
   )
   ```

2. **Update `_parse_single_block()`** to try `_RE_CALL_SITE_NO_FUNC` when `_RE_CALL_SITE` finds no matches.

3. **Optionally extract column** from the `^` caret position (the column index = position of `^` in the line).

4. **Handle the caret + context lines** — lines like `    x = 1 +` and `           ^` should not be treated as call sites or variable sources.

### Expected Behavior After Fix

```
Traceback (most recent call last):
  File "app.py", line 3
    x = 1 +
           ^
SyntaxError: invalid syntax
```

→ `ParsedTrace(file="app.py", line=3, error="SyntaxError: invalid syntax", chain=["app.py:<module>:3"])`

---

## 2. ExceptionGroup / BaseExceptionGroup (Python 3.11+)

### Real-World Format

Python 3.11 introduced `ExceptionGroup` and `BaseExceptionGroup` for handling multiple concurrent exceptions (e.g., `asyncio.TaskGroup`). The traceback format is completely different:

```
  + Exception Group Traceback (most recent call last):
  |   File "app.py", line 10, in main
  |     async with asyncio.TaskGroup() as tg:
  |         tg.create_task(task1())
  |         tg.create_task(task2())
  | ExceptionGroup: unhandled errors in a TaskGroup (2 sub-exceptions)
  +-+---------------- 1 ----------------
    | Traceback (most recent call last):
    |   File "app.py", line 5, in task1
    |     raise ValueError("bad value")
    | ValueError: bad value
    +---------------- 2 ----------------
    | Traceback (most recent call last):
    |   File "app.py", line 8, in task2
    |     raise TypeError("wrong type")
    | TypeError: wrong type
    +------------------------------------
```

Key differences from standard tracebacks:
- **Header**: `+ Exception Group Traceback (most recent call last):` (not just `Traceback ...`)
- **Prefix**: Lines are prefixed with `|` (pipe character)
- **Sub-exceptions**: Separated by `+-+--- N ---` markers
- **Multiple traces**: One ExceptionGroup can contain N sub-exceptions, each with its own traceback

### Why It Fails

1. `_RE_TRACEBACK_HEADER` requires `^Traceback \(most recent call last\):` at the start of a line. The `+ Exception Group Traceback` header doesn't match.

2. Even if the header were matched, the `|` prefix on call-site lines (`|   File "app.py", line 10, in main`) prevents `_RE_CALL_SITE` from matching (it expects `^\s*File`).

3. The nested sub-exceptions have their own `Traceback` headers with `|` prefixes, which also don't match.

### Current Behavior (Verified)

- `can_parse()` returns `False` — completely undetected
- 0 traces parsed for multi-sub-exception groups
- Single-sub-exception fixtures: only the outer `ExceptionGroup` is parsed (1 trace), sub-exceptions are **silently lost**

### What Needs to Change

1. **Extend `_RE_TRACEBACK_HEADER`** to also match `+ Exception Group Traceback`:
   ```python
   _RE_TRACEBACK_HEADER = re.compile(
       r"^(?:\+ )?Traceback \(most recent call last\):", re.MULTILINE
   )
   ```

2. **Strip `|` prefix** before parsing call sites — preprocess lines to remove leading `|` and whitespace.

3. **Parse sub-exception separators** (`+-+--- N ---`) to split into individual sub-traces.

4. **Return multiple `ParsedTrace` objects** — one for the ExceptionGroup itself, plus one per sub-exception.

5. **Add a field to `ParsedTrace`** (optional) for the parent group relationship.

### Expected Behavior After Fix

Input:
```
  + Exception Group Traceback (most recent call last):
  |   File "app.py", line 10, in main
  | ExceptionGroup: unhandled errors (2 sub-exceptions)
  +-+---------------- 1 ----------------
    | Traceback (most recent call last):
    |   File "app.py", line 5, in task1
    |     raise ValueError("bad")
    | ValueError: bad
    +---------------- 2 ----------------
    | Traceback (most recent call last):
    |   File "app.py", line 8, in task2
    |     raise TypeError("wrong")
    | TypeError: wrong
    +------------------------------------
```

→ 3 `ParsedTrace` objects:
- `ParsedTrace(file="app.py", line=10, error="ExceptionGroup: unhandled errors")`
- `ParsedTrace(file="app.py", line=5, error="ValueError: bad")`
- `ParsedTrace(file="app.py", line=8, error="TypeError: wrong")`

---

## 3. Warning Format

### Real-World Format

Python warnings use a different output format than tracebacks:

```
app.py:10: DeprecationWarning: old_function() is deprecated, use new_function()
  result = old_function()
```

```
/usr/lib/python3.12/json/decoder.py:355: JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

Multi-line warnings:

```
app.py:10: ResourceWarning: unclosed <socket.socket fd=3, family=AddressFamily.AF_INET, type=SocketKind.SOCK_STREAM, proto=0, laddr=('127.0.0.1', 54321)>
  result = old_function()
ResourceWarning: Enable tracemalloc to get the object allocation traceback
```

### Why It Fails

- No `Traceback (most recent call last):` header → `can_parse()` returns `False`
- Format is `file:line: WarningType: message` (colon-separated, not `File "x.py", line N`)

### Current Behavior

- Completely undetected by any parser

### What Needs to Change

1. **Create `WarningParser(BaseParser)`** in `parsers/`:
   - Regex: `^(?P<file>[^:]+):(?P<line>\d+):\s*(?P<warning_type>\w+Warning):\s*(?P<msg>.+)$`
   - Also handle `Error` types that use this format (e.g., `JSONDecodeError`)

2. **Add to CLI auto-detection** in `_detect_parser()`.

3. **Map to `ParsedTrace`**: `file`, `line`, `error` = `"{warning_type}: {msg}"`.

### Expected Behavior After Fix

```
app.py:10: DeprecationWarning: old_function() is deprecated
```

→ `ParsedTrace(file="app.py", line=10, error="DeprecationWarning: old_function() is deprecated")`

---

## 4. RecursionError Depth Preservation

### Real-World Format

When Python hits the recursion limit, it abbreviates the traceback:

```
Traceback (most recent call last):
  File "app.py", line 2, in f
    return f()
  File "app.py", line 2, in f
    return f()
  File "app.py", line 2, in f
    return f()
  [Previous line repeated 997 more times]
RecursionError: maximum recursion depth exceeded
```

### Current Behavior

- Parses successfully, but `chain` only contains 3 entries (the 3 shown call sites)
- The `[Previous line repeated 997 more times]` line is silently ignored
- The actual recursion depth (1000) is lost

### What Needs to Change

1. **Detect the repetition line** with regex:
   ```python
   _RE_RECURSION_REPEAT = re.compile(
       r"^\s*\[Previous line repeated (\d+) more times\]",
       re.MULTILINE,
   )
   ```

2. **Store repetition count** — either:
   - Add a `recursion_depth: int | None` field to `ParsedTrace`
   - Or append synthetic entries to `chain` (not recommended — would bloat the chain)

3. **Update `_parse_single_block()`** to scan for this line after collecting call sites.

### Expected Behavior After Fix

→ `ParsedTrace(file="app.py", line=2, error="RecursionError: ...", chain=[...], recursion_depth=1000)`

---

## 5. Exception Notes (Python 3.11+ `add_note()`)

### Real-World Format

Python 3.11 added `Exception.add_note()` to attach metadata to exceptions:

```
Traceback (most recent call last):
  File "app.py", line 10, in process
    result = api.fetch(user_id)
ValueError: bad value
Exception note: This error occurred during the migration phase
```

Multiple notes:

```
Traceback (most recent call last):
  File "app.py", line 10, in process
    result = api.fetch(user_id)
ValueError: bad value
Exception note: User ID was 12345
Exception note: API endpoint was /api/v2/users
```

### Current Behavior

- The exception line (`ValueError: bad value`) is parsed correctly
- The note lines after it are silently ignored
- Notes are lost from the `ParsedTrace`

### What Needs to Change

1. **Detect note lines** — they appear after the exception line, are not indented (or lightly indented), and start with text (not `File` or `Traceback`).

2. **Add `notes: list[str]` field** to `ParsedTrace`.

3. **Parse notes** in `_parse_single_block()` — after matching the exception line, continue scanning for non-indented text lines until the next traceback or end of input.

### Expected Behavior After Fix

→ `ParsedTrace(file="app.py", line=10, error="ValueError: bad value", notes=["User ID was 12345", "API endpoint was /api/v2/users"])`

---

## 6. Logging exc_info Prefix Format

### Real-World Format

Python's `logging` module with `exc_info=True` or `logging.exception()` outputs tracebacks prefixed with timestamp and log level:

```
2024-01-15 10:30:45,123 ERROR [app.main] Traceback (most recent call last):
  File "/app/main.py", line 10, in main
    process()
  File "/app/process.py", line 25, in process
    result = api.fetch(data)
RuntimeError: API connection failed
```

```
2024-01-15T10:30:45 ERROR root Traceback (most recent call last):
  File "worker.py", line 42
    task.run()
  File "task.py", line 15, in run
    self.execute()
ValueError: invalid task state
```

Different logging formatters produce different prefix patterns:
- `logging.Formatter('%(asctime)s %(levelname)s %(name)s')` → `2024-01-15 10:30:45 ERROR [app.main]`
- `logging.Formatter('%(asctime)s %(levelname)s %(module)s')` → `2024-01-15 10:30:45 ERROR main`
- JSON logging → `{"timestamp":"2024-01-15T10:30:45","level":"ERROR","message":"Traceback ..."}`
- Some frameworks put `Traceback` on its own line after the log header

### Why It Fails

The `_RE_TRACEBACK_HEADER` regex uses `^` to anchor at line start:

```python
_RE_TRACEBACK_HEADER = re.compile(
    r"^Traceback \(most recent call last\):", re.MULTILINE
)
```

When `Traceback` is prefixed with `2024-01-15 10:30:45 ERROR ...`, the `^` anchor prevents matching. The entire traceback is invisible to the parser.

### Current Behavior (Verified)

| Scenario | Result |
|----------|--------|
| `Traceback` on same line as log prefix | 0 traces parsed — `can_parse()` returns `False` |
| `Traceback` on separate line after log header | Works correctly — `^` matches at line start |

### What Needs to Change

1. **Relax `_RE_TRACEBACK_HEADER`** — remove `^` anchor or add an alternative:
   ```python
   _RE_TRACEBACK_HEADER = re.compile(
       r"^(?:.*\s)?Traceback \(most recent call last\):", re.MULTILINE
   )
   ```
   Or preprocess: strip log prefixes before parsing.

2. **Be careful with false positives** — `Traceback` in free-form text shouldn't trigger parsing. Consider requiring the next line to be indented and start with `File`.

### Expected Behavior After Fix

```
2024-01-15 10:30:45 ERROR [app.main] Traceback (most recent call last):
  File "/app/main.py", line 10, in main
    process()
RuntimeError: API connection failed
```

→ `ParsedTrace(file="/app/main.py", line=10, error="RuntimeError: API connection failed")`

---

## 7. Re-Raise Annotation (`raise` Without Arguments)

### Real-World Format

Python allows re-raising the current exception with bare `raise`:

```python
try:
    result = api.fetch(data)
except ConnectionError:
    logger.error("API unavailable")
    raise  # re-raises ConnectionError
```

The resulting traceback:

```
Traceback (most recent call last):
  File "app.py", line 5, in fetch_data
    result = api.fetch(data)
ConnectionError: Connection refused

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "app.py", line 3, in main
    fetch_data()
  File "app.py", line 7, in fetch_data
    raise
ConnectionError: Connection refused
```

### Current Behavior

- The parser treats bare `raise` the same as any other traceback
- Both traces are parsed correctly with their call chains
- **No annotation** that the second trace is a re-raise

### What Needs to Change

1. **Detect bare `raise`** — when the source line at the exception origin is just `raise` (no arguments), mark as re-raise.

2. **Add `is_reraise: bool` field** to `ParsedTrace` (optional).

3. **Reproduction context** — for re-raise, the reproduction script should include the `try/except/raise` wrapper, not just the bare `raise`.

### Expected Behavior After Fix

→ `ParsedTrace(file="app.py", line=7, error="ConnectionError: Connection refused", is_reraise=True)`

---

## 8. Doctest Format

### Real-World Format

Python's `doctest` module produces a unique error format:

```
**********************************************************************
File "example.py", line 5, in factorial
Failed example:
    factorial(-1)
Exception raised:
    Traceback (most recent call last):
      File "example.py", line 5, in factorial
        raise ValueError("n must be >= 0")
    ValueError: n must be >= 0
**********************************************************************
```

### Why It Fails

- The `Traceback` header is inside a nested context (after `Exception raised:`)
- Call-site lines have extra indentation (6 spaces instead of 2)
- The surrounding `****` lines and `Failed example:` / `Exception raised:` labels are not part of the traceback

### Current Behavior

- 0 traces parsed — the nested `Traceback` is found but the extra indentation on call-site lines may cause issues

### What Needs to Change

1. **Preprocess**: strip doctest framing (`****` lines, `Failed example:`, `Exception raised:` labels).

2. **Or**: recognize doctest format and extract the embedded traceback.

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Low** | Doctests are rarely the source of production errors |
| Implementation Effort | **Low** | Strip framing, parse embedded traceback |
| Reproduction Value | **Low** | Doctest errors are usually straightforward |

---

## 9. pytest Short Traceback Format

### Real-World Format

pytest shows a short assertion introspection format before the full traceback:

```
FAILED test_example.py::test_divide - assert 2.0 == 3.0

========================= short test summary info =========================
FAILED test_example.py::test_divide - assert 2.0 == 3.0
============================== 1 failed in 0.12s ==============================
```

The full traceback (which pytest also shows) uses standard Python format and IS parsed correctly. Only the short summary is a different format.

### Why It Fails

- No `Traceback (most recent call last):` header
- Format is `FAILED path::test_name - assertion_message`

### Current Behavior

- Short summary: 0 traces parsed (expected — it's not a traceback)
- Full traceback: parsed correctly

### What Needs to Change

- **No change needed for log2repro's primary use case** — the full traceback is what matters for reproduction
- The short format is informational only (test name + assertion)

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Low** | Only relevant for pytest output |
| Implementation Effort | **N/A** | Full traceback already works |
| Reproduction Value | **None** | Short format has no source code context |

---

## 10. LLM API Error JSON Response

### Real-World Format

LLM providers return structured JSON errors via HTTP responses. Each provider has its own format:

**OpenAI style:**
```json
{
  "error": {
    "message": "Invalid API key provided: sk-***...",
    "type": "invalid_request_error",
    "param": null,
    "code": "invalid_api_key"
  }
}
```

**Anthropic style:**
```json
{
  "type": "error",
  "error": {
    "type": "authentication_error",
    "message": "Invalid API Key"
  }
}
```

**LiteLLM unified style:**
```json
{
  "error": {
    "message": "Rate limit exceeded",
    "type": "RateLimitError",
    "code": "429"
  }
}
```

### Why It Fails

- No `Traceback` header → `can_parse()` returns `False` for all parsers
- Format is JSON, not Python traceback text
- Error fields differ across providers (`error.type` vs `error.error.type`)

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **High** | Every LLM integration hits API errors |
| Format Stability | **High** | JSON schema is well-defined per provider |
| Implementation Effort | **Low** | Standard JSON parsing, no complex regex needed |
| Reproduction Value | **Medium** | Can generate retry/fallback code with mocked API response |

### Implementation Notes

1. **Create `APIErrorParser(BaseParser)`**:
   - `can_parse()`: try `json.loads()`, check for `error` key
   - Handle OpenAI, Anthropic, and LiteLLM field variations

2. **Extract into `ParsedTrace`**:
   - `error` = `"{type}: {message}"`
   - `file` / `line` = empty (no source location in API errors)
   - Metadata: `provider`, `error_code`, `error_type`

3. **Reproduction strategy**: generate a mock API response that triggers the same error handling path in user code.

---

## 11. MCP JSON-RPC Error

### Real-World Format

MCP (Model Context Protocol) servers communicate via JSON-RPC 2.0. Errors appear on stderr:

```json
{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"Invalid Request"}}
```

```json
{"jsonrpc":"2.0","id":2,"error":{"code":-32601,"message":"Method not found","data":{"method":"tools/unknown"}}}
```

```json
{"jsonrpc":"2.0","id":3,"error":{"code":-32000,"message":"Server error","data":{"detail":"database connection failed"}}}
```

**Standard JSON-RPC error codes:**
| Code | Meaning |
|------|---------|
| -32700 | Parse error |
| -32600 | Invalid Request |
| -32601 | Method not found |
| -32602 | Invalid params |
| -32603 | Internal error |
| -32000 to -32099 | Server error (reserved) |

### Why It Fails

- JSON format on stderr, no traceback structure
- Mixed with other stderr output (logs, warnings)
- Error codes need mapping to human-readable types

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Medium** | Growing with MCP adoption |
| Format Stability | **High** | JSON-RPC 2.0 is a stable spec |
| Implementation Effort | **Low** | JSON parsing + error code mapping |
| Reproduction Value | **Medium** | Can generate MCP client code with mocked server response |

### Implementation Notes

1. **Create `MCPRpcParser(BaseParser)`**:
   - `can_parse()`: look for `{"jsonrpc":"2.0"` pattern with `"error"` key
   - Extract from mixed stderr: filter lines containing valid JSON-RPC

2. **Map error codes to types**:
   ```python
   _JSONRPC_ERROR_MAP = {
       -32700: "ParseError",
       -32600: "InvalidRequest",
       -32601: "MethodNotFound",
       -32602: "InvalidParams",
       -32603: "InternalError",
   }
   ```

3. **Extract into `ParsedTrace`**:
   - `error` = `"{MappedType}: {message}"`
   - Metadata: `jsonrpc_code`, `method` (if in `data`)

---

## 12. LangChain Agent Verbose Output

### Real-World Format

LangChain agents in verbose mode output a `Thought/Action/Observation` chain:

```
> Entering new AgentExecutor chain...
Thought: I need to search for the user's information
Action: search_database
Action Input: {"query": "user_id=12345"}
Observation: Error: Connection refused to database at localhost:5432
Thought: The database seems to be down, let me try the API instead
Action: call_api
Action Input: {"endpoint": "/users/12345"}
Observation: 404 Client Error: Not Found for url: https://api.example.com/users/12345
Thought: I now know the final answer
Final Answer: Unable to retrieve user information.
> Finished chain.
```

Truncated error format:
```
[AgentError] Tool execution failed: search_database
Error: TimeoutError: connection timed out after 30s
```

### Why It Fails

- No Python traceback — free-form text with structured sections
- Errors are embedded in `Observation` lines, not standalone
- Multiple error types in a single chain (DB, HTTP, timeout)

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Medium** | Common in LangChain/Agent debugging |
| Format Stability | **Low-Medium** | LangChain changes verbose format across versions |
| Implementation Effort | **Medium** | Section-based parsing, not trivial regex |
| Reproduction Value | **High** | Can generate the failing tool call with mocked response |

### Implementation Notes

1. **Create `AgentLogParser(BaseParser)`**:
   - `can_parse()`: look for `Thought:` / `Action:` / `Observation:` patterns
   - Parse the chain into segments

2. **Extract errors from `Observation` lines**:
   - Lines starting with `Error:` or containing HTTP error codes
   - `[AgentError]` prefixed lines

3. **Extract into `ParsedTrace`**:
   - `error` = the error message from the failing Observation
   - `file` / `line` = empty
   - Metadata: `tool_name`, `tool_input`, `chain_steps`

---

## 13. Token / Context Window Limit Errors

### Real-World Format

**Context length exceeded:**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "This model's maximum context length is 128000 tokens. However, your messages resulted in 150000 tokens. Please reduce the length of the messages.", 'type': 'invalid_request_error', 'param': 'messages', 'code': 'context_length_exceeded'}}
```

**Rate limit:**
```
openai.RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for gpt-4 in organization org-xxx on tokens per min (TPM): Limit 10000, Used 9500, Requested 1000. Please try again in 3s.', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
```

**Anthropic style:**
```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'prompt is too long: 200000 tokens > 100000 maximum'}}
```

### Why It Fails

- Looks like a Python exception line but the message is a JSON string embedded in the error
- The actual error details (token count, model name, retry time) are inside the JSON payload
- Current parser extracts the whole string as the error message, losing structured data

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **High** | Very common in LLM applications |
| Format Stability | **Medium** | Message format varies but always includes token counts |
| Implementation Effort | **Low** | Regex or JSON extraction from known patterns |
| Reproduction Value | **High** | Can generate code that truncates input to fit context |

### Implementation Notes

1. **Create `LLMErrorParser(BaseParser)`**:
   - `can_parse()`: match patterns like `token`, `context_length`, `rate_limit` in error text
   - Extract structured data from embedded JSON

2. **Parse token counts and limits**:
   ```python
   _RE_TOKEN_ERROR = re.compile(
       r"(?:maximum context length|context_length_exceeded).*?(\d+)\s*tokens"
   )
   _RE_RATE_LIMIT = re.compile(
       r"Rate limit.*?try again in (\d+)(s|ms)"
   )
   ```

3. **Extract into `ParsedTrace`**:
   - `error` = `"{ErrorType}: {human_readable_summary}"`
   - Metadata: `model`, `token_used`, `token_limit`, `retry_after`

---

## 14. Agent Tool Execution Error (Truncated Format)

### Real-World Format

Agent frameworks often truncate tool errors for brevity:

```
[AgentError] Tool execution failed: web_search
Error: HTTPConnectionPool(host='search.example.com', port=80): Max retries exceeded with url: /search?q=test (Caused by NewConnectionError('<urllib3.connection.HTTPConnection object>: Failed to establish a new connection: [Errno 111] Connection refused'))
```

```
[ToolError] Failed to execute tool: code_interpreter
Output: MemoryError: Unable to allocate 2.00 GiB for an array with shape (500000000,) and data type float64
```

```
[AgentError] Tool execution timed out after 60s: database_query
```

### Why It Fails

- The `[AgentError]` / `[ToolError]` prefix is not a standard Python traceback format
- The actual error is on a subsequent line, often with different indentation
- Timeout errors have no exception type — just a message

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Medium** | Common in agent debugging |
| Format Stability | **Low** | Framework-specific prefixes |
| Implementation Effort | **Low** | Simple prefix + content extraction |
| Reproduction Value | **High** | Can generate the failing tool call |

### Implementation Notes

1. **Extend `AgentLogParser`** or create separate handler:
   - Match `[AgentError]`, `[ToolError]` prefixes
   - Extract tool name from "Tool execution failed: {name}"
   - Capture subsequent error lines

2. **Extract into `ParsedTrace`**:
   - `error` = the embedded error message
   - Metadata: `tool_name`, `is_timeout`

---

## 15. SSE Streaming Error Chunks

### Real-World Format

LLM streaming APIs send errors as SSE (Server-Sent Events) chunks:

```
data: {"error":{"message":"The server had an error processing your request","type":"server_error","code":null}}
```

```
event: error
data: {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}
```

Mixed with normal stream:
```
data: {"choices":[{"delta":{"content":"Hello"}}]}

data: {"choices":[{"delta":{"content":" world"}}]}

data: [DONE]

data: {"error":{"message":"Request timed out","type":"timeout","code":"timeout"}}
```

### Why It Fails

- SSE format (`data: ` prefix) is not recognized by any parser
- Errors mixed with normal stream data
- JSON embedded after `data: ` prefix

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Medium** | All streaming LLM calls |
| Format Stability | **High** | SSE is a well-defined spec |
| Implementation Effort | **Low** | Strip `data: ` prefix, parse JSON |
| Reproduction Value | **Medium** | Can generate non-streaming equivalent that triggers same error |

### Implementation Notes

1. **Extend `APIErrorParser`** to handle SSE format:
   - Strip `data: ` and `event: ` prefixes
   - Parse remaining JSON for error objects
   - Filter out `data: [DONE]`

2. **Extract into `ParsedTrace`**:
   - Same as §10 LLM API Error JSON
   - Metadata: `is_streaming=True`

---

## 16. Image / Vision API Errors

### Real-World Format

Vision API errors have unique patterns:

```
openai.BadRequestError: Error code: 400 - {'error': {'message': 'Invalid image URL: Unable to download image from https://example.com/invalid.jpg', 'type': 'invalid_request_error', 'param': 'messages[0].content[1].image_url.url', 'code': 'invalid_image_url'}}
```

```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Image exceeds maximum size of 20MB. Received: 25.3MB'}}
```

```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid MIME type 'application/pdf' for image content. Supported types: image/png, image/jpeg, image/gif, image/webp", 'type': 'invalid_request_error', 'code': 'invalid_image_format'}}
```

### Why It Fails

- Same as §10 — JSON error format, not a Python traceback
- Unique error types not covered by standard LLM error patterns
- Error messages reference specific media constraints

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Medium** | Growing with multi-modal adoption |
| Format Stability | **High** | Same JSON structure as §10 |
| Implementation Effort | **Low** | Handled by `APIErrorParser` from §10 |
| Reproduction Value | **Medium** | Can generate code with valid image/invalid image |

### Implementation Notes

- **No separate parser needed** — handled by `APIErrorParser` (§10)
- **Add multi-modal error codes** to the error type mapping:
  - `invalid_image_url`, `invalid_image_format`, `image_too_large`
- **Metadata**: `media_type`, `file_size`, `param` (points to the problematic content part)

---

## 17. Google Gemini API Errors

### Real-World Format

Google's Gemini API uses `google.api_core.exceptions` classes and a distinct JSON error format:

**HTTP response body:**
```json
{
  "error": {
    "code": 400,
    "message": "Invalid value at 'contents[0].parts[0].text' (TYPE_STRING), \"\"",
    "status": "INVALID_ARGUMENT",
    "details": [{"@type": "type.googleapis.com/google.rpc.BadRequest", "fieldViolations": [...]}]
  }
}
```

**Python SDK exception:**
```
google.api_core.exceptions.InvalidArgument: 400 Invalid value at 'contents[0].parts[0].text' (TYPE_STRING), ""
```

**`google-genai` SDK (v1.x):**
```
google.genai.errors.ClientError: 400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': '...', 'status': 'INVALID_ARGUMENT'}}
```

**Common error types:**
| Exception Class | HTTP Status | gRPC Status |
|---|---|---|
| `BadRequest` / `InvalidArgument` | 400 | INVALID_ARGUMENT |
| `Forbidden` / `PermissionDenied` | 403 | PERMISSION_DENIED |
| `NotFound` | 404 | NOT_FOUND |
| `TooManyRequests` / `ResourceExhausted` | 429 | RESOURCE_EXHAUSTED |
| `InternalServerError` | 500 | INTERNAL |
| `ServiceUnavailable` | 503 | UNAVAILABLE |

### Why It Fails

- Error format is Google-specific (`error.code` + `error.status` + `error.details`), not OpenAI/Anthropic style
- Python exceptions use `google.api_core.exceptions` hierarchy, not standard HTTP error classes
- `google-genai` SDK wraps errors in `ClientError`/`ServerError` with combined message format

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **High** | Third-largest LLM provider |
| Format Stability | **High** | Google API error format is well-established |
| Implementation Effort | **Low** | JSON parsing + exception class mapping |
| Reproduction Value | **Medium** | Can generate retry/fallback code with mocked response |

### Implementation Notes

1. **Extend `APIErrorParser`** or create `GeminiErrorParser`:
   - Parse Google JSON error format (`error.code`, `error.status`, `error.message`)
   - Map `google.api_core.exceptions` class names to error types
   - Handle `google-genai` SDK's `ClientError`/`ServerError` wrapper

2. **Extract into `ParsedTrace`**:
   - `error` = `"{status}: {message}"`
   - Metadata: `grpc_status`, `http_code`, `provider="google"`

---

## 18. A2A Protocol Errors (Agent-to-Agent)

### Real-World Format

Google's A2A (Agent-to-Agent) protocol uses JSON-RPC 2.0 with 5 protocol-specific error codes:

```json
{
  "jsonrpc": "2.0",
  "id": "task-123",
  "error": {
    "code": -32001,
    "message": "Task not found",
    "data": {"task_id": "task-123"}
  }
}
```

**A2A-specific error codes:**
| Code | Name | Description |
|------|------|-------------|
| -32001 | Task not found | Referenced task doesn't exist |
| -32002 | Task cannot be canceled | Task not in a cancelable state |
| -32003 | Push notification not supported | Agent doesn't support push notifications |
| -32004 | Unsupported operation | Operation not supported by this agent |
| -32005 | Content type not supported | Agent can't handle the requested content type |

Plus standard JSON-RPC codes: -32700 (Parse error), -32600 (Invalid Request), -32601 (Method not found), -32602 (Invalid params), -32603 (Internal error).

### Why It Fails

- Same as MCP (§11) — JSON-RPC format, no Python traceback
- A2A-specific codes (-32001 to -32005) not in standard JSON-RPC error code tables
- Errors appear in HTTP response bodies or WebSocket messages

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Medium** | New protocol, growing adoption alongside MCP |
| Format Stability | **High** | JSON-RPC 2.0 is stable; A2A codes are in the spec |
| Implementation Effort | **Low** | Extend MCP parser with A2A-specific code mapping |
| Reproduction Value | **Medium** | Can generate A2A client code with mocked agent response |

### Implementation Notes

1. **Extend `MCPRpcParser`** or create `A2AErrorParser`:
   - Parse JSON-RPC 2.0 error format (same as MCP)
   - Add A2A-specific error code mapping (-32001 to -32005)
   - Detect A2A context from request/response metadata

2. **Extract into `ParsedTrace`**:
   - `error` = `"{MappedType}: {message}"`
   - Metadata: `protocol="a2a"`, `jsonrpc_code`, `task_id`

---

## 19. Content Moderation / Safety Filter Errors

### Real-World Format

**OpenAI:**
```json
{
  "error": {
    "message": "Your request was rejected as a result of our safety system. Your prompt may contain text that is not allowed by our safety system.",
    "type": "invalid_request_error",
    "param": null,
    "code": "content_policy_violation"
  }
}
```

**Anthropic:**
```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Output blocked by content filtering policy'}}
```

**Google Gemini:**
```
google.api_core.exceptions.InvalidArgument: 400 Request contains potentially harmful content (SAFETY)
```

**LiteLLM:**
```python
litellm.ContentPolicyViolationError: OpenAIException: Your request was rejected as a result of our safety system.
```

### Why It Fails

- These are API errors (handled by §10 `APIErrorParser`), but the `code`/`type` varies:
  - OpenAI: `code: "content_policy_violation"`
  - Anthropic: embedded in message text
  - Google: `SAFETY` in message
  - LiteLLM: `ContentPolicyViolationError` exception class
- The safety category information is often embedded in the message, not structured

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **High** | Common with user-generated content |
| Format Stability | **Medium** | Provider-specific codes, message format varies |
| Implementation Effort | **Low** | Extend `APIErrorParser` with content policy detection |
| Reproduction Value | **Medium** | Can generate code that tests content policy boundaries |

### Implementation Notes

1. **Extend `APIErrorParser`** to detect content policy errors:
   - Check for `content_policy_violation` code (OpenAI)
   - Check for `safety` / `content filtering` in message (Anthropic, Google)
   - Check for `ContentPolicyViolationError` class (LiteLLM)

2. **Extract into `ParsedTrace`**:
   - `error` = `"ContentPolicyViolation: {message}"`
   - Metadata: `provider`, `violation_category` (if extractable)

---

## 20. Tool Calling / Function Calling Errors

### Real-World Format

**JSON Schema validation failure (OpenAI strict mode):**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid schema for function 'get_weather': In context=('properties', 'date'), 'format' is not supported in strict mode. Use 'pattern' instead.", 'type': 'invalid_request_error', 'param': 'tools[0].function.parameters', 'code': 'invalid_schema'}}
```

**Tool parameter type mismatch:**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid parameter: 'temperature' must be a number, got string", 'type': 'invalid_request_error', 'param': 'temperature', 'code': 'invalid_type'}}
```

**OpenAI Assistants API — run requires action:**
```json
{
  "id": "run_abc123",
  "object": "thread.run",
  "status": "requires_action",
  "required_action": {
    "type": "submit_tool_outputs",
    "submit_tool_outputs": {
      "tool_calls": [{"id": "call_abc", "function": {"name": "get_weather", "arguments": "{\"city\":\"NYC\"}"}}]
    }
  }
}
```

**Tool output formatting error:**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid tool call output: expected JSON, got 'success'", 'type': 'invalid_request_error', 'code': 'invalid_tool_output'}}
```

### Why It Fails

- Schema validation errors are API errors (handled by §10), but the error message references specific JSON Schema fields
- `requires_action` status is not an error — it's a control flow signal in the Assistants API
- Tool output formatting errors have a distinct `code: "invalid_tool_output"`

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **High** | Every tool-calling integration hits these |
| Format Stability | **Medium** | OpenAI's strict mode schema restrictions change |
| Implementation Effort | **Low** | Extend `APIErrorParser` with tool-specific codes |
| Reproduction Value | **High** | Can generate corrected schema/tool call code |

### Implementation Notes

1. **Extend `APIErrorParser`** to detect tool calling errors:
   - Check for `invalid_schema`, `invalid_type`, `invalid_tool_output` codes
   - Parse `param` field to identify which tool/parameter failed
   - Detect `requires_action` status in Assistants API responses

2. **Extract into `ParsedTrace`**:
   - `error` = `"{code}: {message}"`
   - Metadata: `tool_name`, `param`, `schema_field`

---

## 21. OpenAI Responses API Errors

### Real-World Format

The Responses API (March 2025) uses SSE events for streaming. Errors arrive as `response.failed` events:

```
event: response.failed
data: {"type":"response.failed","response":{"id":"resp_abc","object":"response","status":"failed","error":{"type":"server_error","code":"internal_error","message":"An internal error occurred"}}}
```

**Non-streaming error:**
```json
{
  "id": "resp_abc",
  "object": "response",
  "status": "failed",
  "error": {
    "type": "invalid_request_error",
    "code": "invalid_parameter",
    "message": "The 'model' parameter is required"
  }
}
```

**Status values:** `completed`, `failed`, `cancelled`, `expired`

### Why It Fails

- Error is nested inside a `response.failed` SSE event, not a simple JSON error
- The error object structure is the same as Chat Completions, but the envelope is different
- Streaming errors require parsing SSE events before extracting the error

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Medium** | New API, growing adoption |
| Format Stability | **High** | OpenAI's new standard API |
| Implementation Effort | **Low** | Extend SSE parser (§15) with Responses API envelope |
| Reproduction Value | **Medium** | Can generate non-streaming equivalent |

### Implementation Notes

1. **Extend `APIErrorParser`** to handle Responses API envelope:
   - Parse SSE events, detect `response.failed` type
   - Extract `response.error` object (same structure as Chat Completions errors)
   - Handle non-streaming `status: "failed"` responses

2. **Extract into `ParsedTrace`**:
   - Same as §10 LLM API Error JSON
   - Metadata: `api="responses"`, `response_id`, `status`

---

## 22. Agent Framework Errors (CrewAI / AutoGen / Google ADK / Semantic Kernel)

### Real-World Format

**CrewAI:**
```
crewai.exceptions.AgentExecutionError: Agent 'Researcher' failed to complete task: LLM rate limit exceeded after 3 retries
```
```
crewai.exceptions.CrewError: Crew execution failed: All agents failed to complete their tasks
```

**AutoGen (Microsoft):**
```
autogen.exceptions.TerminationException: Group chat terminated: max_rounds (10) reached without consensus
```
```
autogen.exceptions.GroupChatError: Agent 'critic' raised an unexpected error: API connection failed
```

**Google ADK:**
```
google.adk.errors.ToolError: Tool 'search_web' execution failed: HTTP 429 Too Many Requests
```
```
google.adk.errors.AgentError: Agent 'planner' failed: Unable to parse LLM response as valid JSON
```

**Semantic Kernel (Microsoft):**
```
semantic_kernel.exceptions.KernelInvokeError: Function 'SearchPlugin.Search' invocation failed: OpenAI rate limit exceeded
```

### Why It Fails

- Each framework wraps LLM/tool errors in its own exception hierarchy
- The original LLM error is nested in the exception message or `__cause__`
- Different frameworks use different naming: `AgentExecutionError`, `TerminationException`, `ToolError`, `KernelInvokeError`

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Medium** | Common in agent debugging |
| Format Stability | **Low** | Framework APIs change frequently |
| Implementation Effort | **Medium** | Need to detect multiple framework patterns |
| Reproduction Value | **High** | Can generate the failing agent/tool call |

### Implementation Notes

1. **Create `AgentFrameworkParser(BaseParser)`**:
   - `can_parse()`: detect framework-specific exception class names
   - Parse the framework error wrapper, extract the underlying error
   - Support CrewAI, AutoGen, Google ADK, Semantic Kernel

2. **Extract into `ParsedTrace`**:
   - `error` = the underlying error (e.g., "LLM rate limit exceeded")
   - Metadata: `framework`, `agent_name`, `original_error_type`

---

## 23. LiteLLM Unified Exception System

### Real-World Format

LiteLLM defines 8 exception classes that map to all provider errors:

```python
import litellm

try:
    response = litellm.completion(model="gpt-4", messages=[...])
except litellm.AuthenticationError as e:
    # 401 — all providers
    print(f"Auth failed: {e.message}")
except litellm.RateLimitError as e:
    # 429 — all providers
    print(f"Rate limited: {e.message}, retry after {e.retry_after}s")
except litellm.ContextWindowExceededError as e:
    # 400 — token limit
    print(f"Context too long: {e.message}")
except litellm.BudgetExceededError as e:
    # 429 — budget limit
    print(f"Budget exceeded: {e.message}")
except litellm.ContentPolicyViolationError as e:
    # 400 — safety filter
    print(f"Content blocked: {e.message}")
except litellm.InvalidRequestError as e:
    # 400 — bad request
    print(f"Invalid request: {e.message}")
except litellm.ServiceUnavailableError as e:
    # 503 — provider down
    print(f"Service unavailable: {e.message}")
except litellm.Timeout as e:
    # 408 — timeout
    print(f"Timeout: {e.message}")
```

**LiteLLM Proxy unified JSON error:**
```json
{
  "error": {
    "message": "Rate limit exceeded for gpt-4",
    "type": "RateLimitError",
    "code": "429",
    "param": null
  }
}
```

### Why It Fails

- LiteLLM's exception classes are not standard HTTP errors — they're a unified mapping layer
- The proxy's JSON format is similar to OpenAI but uses LiteLLM's `type` values (e.g., `RateLimitError` vs `rate_limit_error`)
- §10 covers the basic JSON format but not the full exception hierarchy

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **High** | LiteLLM is the most popular LLM gateway/proxy |
| Format Stability | **High** | Stable exception hierarchy |
| Implementation Effort | **Low** | Map LiteLLM exception names to error types |
| Reproduction Value | **Medium** | Can generate retry/fallback code |

### Implementation Notes

1. **Extend `APIErrorParser`** to recognize LiteLLM exception names:
   ```python
   _LITELLM_ERROR_MAP = {
       "AuthenticationError": "authentication",
       "RateLimitError": "rate_limit",
       "ContextWindowExceededError": "context_window",
       "BudgetExceededError": "budget_exceeded",
       "ContentPolicyViolationError": "content_policy",
       "InvalidRequestError": "invalid_request",
       "ServiceUnavailableError": "service_unavailable",
       "Timeout": "timeout",
   }
   ```

2. **Extract into `ParsedTrace`**:
   - `error` = `"{MappedType}: {message}"`
   - Metadata: `provider` (from LiteLLM), `original_error_type`

---

## 24. Anthropic Extended Thinking Errors

### Real-World Format

```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'thinking.budget_tokens: must be less than max_tokens'}}
```

```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'thinking.type: must be enabled when streaming thinking content'}}
```

```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Extended thinking is not supported for model claude-3-5-sonnet-20241022'}}
```

### Why It Fails

- These are standard Anthropic API errors (handled by §10), but with thinking-specific messages
- The `thinking.*` parameter path in the error message is unique to this feature

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Low** | Extended thinking is a newer feature |
| Format Stability | **Low** | Feature is evolving |
| Implementation Effort | **None** | Already handled by §10 `APIErrorParser` |
| Reproduction Value | **Low** | Can generate corrected thinking config |

### Implementation Notes

- **No separate parser needed** — handled by `APIErrorParser` (§10)
- **Add thinking-specific error detection** to metadata: `feature="extended_thinking"` when message contains `thinking.*`

---

## 25. Embedding API Errors

### Real-World Format

**OpenAI:**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "This model's maximum context length is 8191 tokens, however you sent 10000 tokens", 'type': 'invalid_request_error', 'param': 'input', 'code': 'context_length_exceeded'}}
```

**Dimension mismatch:**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid 'dimensions' param: requested 256 but model outputs 1536 dimensions", 'type': 'invalid_request_error', 'param': 'dimensions', 'code': 'invalid_value'}}
```

**Batch size exceeded:**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Too many inputs. Maximum 2048, got 5000", 'type': 'invalid_request_error', 'param': 'input', 'code': 'too_many_inputs'}}
```

### Why It Fails

- Standard API errors (handled by §10), but with embedding-specific error codes and parameters
- The `param` field points to embedding-specific parameters (`input`, `dimensions`)

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Medium** | Common in RAG/vector search applications |
| Format Stability | **High** | Same as §10 |
| Implementation Effort | **None** | Already handled by §10 `APIErrorParser` |
| Reproduction Value | **Medium** | Can generate corrected embedding call |

### Implementation Notes

- **No separate parser needed** — handled by `APIErrorParser` (§10)
- **Add embedding-specific metadata**: `api="embeddings"`, `input_tokens`, `requested_dimensions`

---

## 26. Batch API Errors

### Real-World Format

**OpenAI Batch API — batch failed status:**
```json
{
  "id": "batch_abc123",
  "object": "batch",
  "status": "failed",
  "errors": {
    "data": [{"code": "invalid_jsonl", "message": "Line 5: Invalid JSON object", "line": 5}],
    "object": "list"
  },
  "request_counts": {"total": 100, "completed": 95, "failed": 5}
}
```

**Individual request failure in batch output:**
```json
{"id": "batch_req_001", "response": {"status_code": 400, "body": {"error": {"message": "...", "type": "invalid_request_error"}}}, "error": null}
{"id": "batch_req_002", "response": null, "error": {"code": "rate_limit_exceeded", "message": "Rate limit exceeded"}}
```

### Why It Fails

- Batch errors have a different envelope: `status: "failed"` + `errors.data` array
- Individual request failures in batch output have `response.status_code` or `error` fields
- The batch-level error is not a standard API error response

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Low** | Batch API is less commonly used |
| Format Stability | **High** | OpenAI Batch API is stable |
| Implementation Effort | **Low** | Parse batch status JSON, extract error summary |
| Reproduction Value | **Low** | Batch errors are usually input data issues |

### Implementation Notes

1. **Extend `APIErrorParser`** to detect batch errors:
   - Parse `status: "failed"` + `errors.data` array
   - Extract error summary (count, first error message)

2. **Extract into `ParsedTrace`**:
   - `error` = `"BatchError: {first_error_message}"`
   - Metadata: `batch_id`, `total`, `failed_count`

---

## 27. Realtime API WebSocket Errors

### Real-World Format

OpenAI's Realtime API sends errors as WebSocket messages:

```json
{
  "type": "error",
  "event_id": "event_abc123",
  "error": {
    "type": "invalid_request_error",
    "code": "invalid_event",
    "message": "Invalid event type 'foo': not a recognized event",
    "param": "type",
    "event_id": "event_abc123"
  }
}
```

**Connection-level error:**
```json
{
  "type": "error",
  "error": {
    "type": "server_error",
    "code": "connection_error",
    "message": "WebSocket connection failed: timeout after 30s"
  }
}
```

**Session-level error:**
```json
{
  "type": "session.error",
  "error": {
    "type": "invalid_request_error",
    "code": "session_limit_exceeded",
    "message": "Maximum session duration (30min) exceeded"
  }
}
```

### Why It Fails

- WebSocket messages are not HTTP responses — no status codes
- Error envelope uses `"type": "error"` or `"type": "session.error"`
- Error object structure is similar to OpenAI HTTP errors but with additional fields (`event_id`, `param`)

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Low** | Realtime API is new, limited adoption |
| Format Stability | **Medium** | API is evolving |
| Implementation Effort | **Low** | Parse WebSocket JSON messages with error type |
| Reproduction Value | **Low** | Realtime API errors are usually connection issues |

### Implementation Notes

1. **Extend `APIErrorParser`** to handle WebSocket error messages:
   - Detect `"type": "error"` or `"type": "session.error"` in JSON
   - Extract nested `error` object (same structure as HTTP errors)

2. **Extract into `ParsedTrace`**:
   - `error` = `"{code}: {message}"`
   - Metadata: `transport="websocket"`, `event_id`

---

## 28. Audio API Errors (Whisper / TTS / Realtime Voice)

### Real-World Format

**Whisper transcription — unsupported codec:**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid file format. Supported formats: ['flac', 'm4a', 'mp3', 'mp4', 'mpeg', 'mpga', 'oga', 'ogg', 'wav', 'webm']", 'type': 'invalid_request_error', 'param': 'file', 'code': 'invalid_file_format'}}
```

**Whisper — file too large:**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': 'File size exceeds maximum of 25MB', 'type': 'invalid_request_error', 'param': 'file', 'code': 'file_too_large'}}
```

**TTS — invalid voice:**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid voice: 'custom_voice'. Available voices: alloy, echo, fable, onyx, nova, shimmer", 'type': 'invalid_request_error', 'param': 'voice', 'code': 'invalid_value'}}
```

**TTS — input too long:**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': 'Input text is too long. Maximum 4096 characters, got 5000', 'type': 'invalid_request_error', 'param': 'input', 'code': 'max_characters_exceeded'}}
```

**Realtime Voice — audio format error:**
```json
{
  "type": "error",
  "error": {
    "type": "invalid_request_error",
    "code": "invalid_audio_format",
    "message": "Unsupported audio format: expected PCM16 at 24kHz, got 8kHz"
  }
}
```

### Why It Fails

- Standard API errors (handled by §10 `APIErrorParser`), but with audio-specific error codes
- Audio API endpoints have unique parameters (`file`, `voice`, `input`, `response_format`)
- Realtime Voice errors use WebSocket format (§27)

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Medium** | Common in speech-to-text / text-to-speech apps |
| Format Stability | **High** | Same as §10 |
| Implementation Effort | **None** | Already handled by §10 `APIErrorParser` |
| Reproduction Value | **Medium** | Can generate corrected audio API call |

### Implementation Notes

- **No separate parser needed** — handled by `APIErrorParser` (§10)
- **Add audio-specific metadata**: `api="audio"`, `endpoint="transcriptions"|"speech"`, `file_format`, `voice`

---

## 29. Document / PDF Input Errors

### Real-World Format

**Anthropic — PDF too large:**
```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Document size exceeds maximum of 10MB. Received: 15.2MB'}}
```

**Anthropic — invalid document encoding:**
```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Invalid document: could not decode base64 content'}}
```

**Anthropic — unsupported document type:**
```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': "Unsupported document media type: 'application/msword'. Supported: application/pdf"}}
```

**Google Gemini — file upload MIME error:**
```
google.api_core.exceptions.InvalidArgument: 400 Unsupported MIME type: 'application/epub+zip'
```

**Google Gemini — file upload size error:**
```
google.api_core.exceptions.InvalidArgument: 400 File size exceeds maximum of 2GB
```

**OpenAI Assistants — file upload error:**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid file type: 'application/pdf'. Supported types for this endpoint: ['text/plain', 'text/csv', 'application/json']", 'type': 'invalid_request_error', 'param': 'file', 'code': 'invalid_file_type'}}
```

### Why It Fails

- Each provider has different document support: Anthropic (PDF via `document` block), Gemini (any file via `files.upload()`), OpenAI (text files via Assistants)
- Error format is provider-specific but follows their standard API error pattern
- Document-specific parameters (`media_type`, `file_size`, `base64` encoding)

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Medium** | Growing with document processing use cases |
| Format Stability | **High** | Same as §10 per provider |
| Implementation Effort | **None** | Already handled by §10 `APIErrorParser` |
| Reproduction Value | **Medium** | Can generate corrected document upload code |

### Implementation Notes

- **No separate parser needed** — handled by `APIErrorParser` (§10)
- **Add document-specific metadata**: `media_type`, `file_size`, `encoding="base64"`, `provider`

---

## 30. Google Gemini Multi-Modal Errors

### Real-World Format

**Video upload — unsupported format:**
```
google.api_core.exceptions.InvalidArgument: 400 Unsupported MIME type: 'video/avi'. Supported: video/mp4, video/mov, video/webm
```

**Video — duration too long:**
```
google.api_core.exceptions.InvalidArgument: 400 Video duration exceeds maximum of 2 hours. Received: 3h 15m
```

**Video — processing failed:**
```
google.api_core.exceptions.InternalServerError: 500 Failed to process video: frame extraction failed at 45.2s
```

**Audio — unsupported format:**
```
google.api_core.exceptions.InvalidArgument: 400 Unsupported MIME type: 'audio/aac'. Supported: audio/mpeg, audio/wav, audio/ogg, audio/flac
```

**File API — upload failed:**
```
google.api_core.exceptions.InvalidArgument: 400 Invalid file URI: 'gs://bucket/file.mp4'. Expected format: files/{file_id}
```

**File API — file not ready:**
```
google.api_core.exceptions.FailedPrecondition: 400 File 'files/abc123' is still processing. Status: PROCESSING
```

**Multi-modal token overflow:**
```
google.api_core.exceptions.InvalidArgument: 400 Total token count (250000) exceeds model limit (1048576). Note: video tokens are calculated at 1 token per second.
```

### Why It Fails

- Google Gemini has the broadest multi-modal support (image, video, audio, PDF) with a unique File API
- File processing is asynchronous — files go through `PROCESSING` → `ACTIVE` states
- Token counting differs per media type (video: 1 token/sec, image: based on resolution)
- Error format follows Google API pattern (§17), but with multi-modal specific messages

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Medium** | Growing with Gemini multi-modal adoption |
| Format Stability | **High** | Google API error format |
| Implementation Effort | **None** | Handled by §17 `GeminiErrorParser` |
| Reproduction Value | **Medium** | Can generate corrected multi-modal API call |

### Implementation Notes

- **No separate parser needed** — handled by `GeminiErrorParser` (§17)
- **Add multi-modal metadata**: `media_type`, `file_id`, `processing_status`, `duration`, `token_count`

---

## 31. Image Generation API Errors (DALL-E / Imagen)

### Real-World Format

**DALL-E — content policy violation (generation-specific):**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': 'Your request was rejected by the safety system. The prompt contains content that violates our usage policies.', 'type': 'invalid_request_error', 'param': 'prompt', 'code': 'content_policy_violation'}}
```

**DALL-E — invalid size:**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid size: '1920x1080'. Supported sizes for dall-e-3: 1024x1024, 1792x1024, 1024x1792", 'type': 'invalid_request_error', 'param': 'size', 'code': 'invalid_value'}}
```

**DALL-E — prompt too long:**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': 'Prompt is too long. Maximum 4000 characters for dall-e-3, got 5000', 'type': 'invalid_request_error', 'param': 'prompt', 'code': 'max_length_exceeded'}}
```

**DALL-E — rate limit (generation-specific):**
```
openai.RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for images per minute. Limit: 5 images/min for dall-e-3.', 'type': 'rate_limit_error', 'code': 'rate_limit_exceeded'}}
```

**Imagen — invalid parameter:**
```
google.api_core.exceptions.InvalidArgument: 400 Invalid aspect ratio: '3:2'. Supported: 1:1, 3:4, 4:3, 9:16, 16:9
```

### Why It Fails

- Standard API errors (handled by §10 / §17), but with generation-specific parameters
- Content policy violations for generation have different triggers than chat
- Generation endpoints have unique parameters (`size`, `quality`, `style`, `n`, `response_format`)

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Medium** | Common in image generation apps |
| Format Stability | **High** | Same as §10 / §17 |
| Implementation Effort | **None** | Handled by `APIErrorParser` (§10) / `GeminiErrorParser` (§17) |
| Reproduction Value | **Medium** | Can generate corrected generation call |

### Implementation Notes

- **No separate parser needed** — handled by §10 / §17
- **Add generation-specific metadata**: `api="images"`, `model="dall-e-3"`, `size`, `quality`, `style`

---

## 32. Video Understanding Errors

### Real-World Format

**Gemini — video too long:**
```
google.api_core.exceptions.InvalidArgument: 400 Video duration (3h 15m) exceeds maximum supported duration (2h) for model gemini-2.5-flash
```

**Gemini — video format not supported:**
```
google.api_core.exceptions.InvalidArgument: 400 Unsupported video codec: 'hevc'. Supported: h264, vp8, vp9
```

**Gemini — video frame extraction failed:**
```
google.api_core.exceptions.InternalServerError: 500 Failed to extract frames from video: corrupted video data at offset 45.2MB
```

**Gemini — video too large:**
```
google.api_core.exceptions.InvalidArgument: 400 Video file size (5.2GB) exceeds maximum (2GB) for inline upload. Use File API instead.
```

### Why It Fails

- Video understanding is a Gemini-specific feature with unique constraints
- Errors follow Google API format (§17) but with video-specific messages
- Video processing can fail at multiple stages (upload, codec validation, frame extraction, token counting)

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Low** | Video understanding is a newer feature |
| Format Stability | **High** | Google API error format |
| Implementation Effort | **None** | Handled by §17 `GeminiErrorParser` |
| Reproduction Value | **Low** | Video errors are usually data issues |

### Implementation Notes

- **No separate parser needed** — handled by `GeminiErrorParser` (§17)
- **Add video metadata**: `media_type="video"`, `duration`, `codec`, `file_size`

---

## 33. Multi-Modal Token Counting Errors

### Real-World Format

**OpenAI — image token overflow:**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "This model's maximum context length is 128000 tokens. Your messages with images resulted in 150000 tokens. Image tokens are calculated based on resolution: a 1024x1024 image uses approximately 765 tokens.", 'type': 'invalid_request_error', 'param': 'messages', 'code': 'context_length_exceeded'}}
```

**Gemini — video token overflow:**
```
google.api_core.exceptions.InvalidArgument: 400 Total token count (500000) exceeds model limit (1048576). Video tokens: 1 token per second of video. Your 2-hour video uses approximately 7200 tokens.
```

**Gemini — mixed media token calculation:**
```
google.api_core.exceptions.InvalidArgument: 400 Input contains mixed media types. Total tokens: 250000 (text: 5000, images: 20000, video: 225000). Exceeds model limit of 200000.
```

**Anthropic — image token limit:**
```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Total input tokens (150000) exceeds maximum (200000). Note: image tokens are calculated based on image dimensions.'}}
```

### Why It Fails

- Multi-modal token counting is provider-specific:
  - OpenAI: image tokens based on resolution (tile-based calculation)
  - Gemini: video = 1 token/sec, image = resolution-based, different per model
  - Anthropic: image tokens based on dimensions
- Error messages include token breakdowns but in unstructured text
- Standard context window errors (§13) don't capture media-specific token info

### Supportability Assessment

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Frequency | **Medium** | Common with multi-modal inputs |
| Format Stability | **Medium** | Token calculation rules change per model version |
| Implementation Effort | **Low** | Extend §13 `LLMErrorParser` with media token extraction |
| Reproduction Value | **Medium** | Can generate code that reduces media input to fit |

### Implementation Notes

1. **Extend `LLMErrorParser` (§13)** to parse media token breakdowns:
   - Extract token counts per media type from error messages
   - Parse image/video/audio-specific token calculation hints

2. **Extract into `ParsedTrace`**:
   - `error` = `"ContextWindowExceeded: {token_summary}"`
   - Metadata: `text_tokens`, `image_tokens`, `video_tokens`, `audio_tokens`, `media_type`

---

## Summary Table

| # | Format | Parser Impact | Complexity | Reproduction Value | Priority |
|---|--------|--------------|------------|-------------------|----------|
| 1 | SyntaxError caret | `_RE_CALL_SITE` + `_parse_single_block` | Medium | High | **P1** |
| 2 | ExceptionGroup | New header + `|` prefix stripping | High | High | **P1** |
| 3 | Warning format | New `WarningParser` class | Low | Low | P3 |
| 4 | RecursionError depth | New regex + `ParsedTrace` field | Low | Medium | P3 |
| 5 | Exception notes | New regex + `ParsedTrace.notes` | Low | Medium | P2 |
| 6 | Logging exc_info prefix | Relax `_RE_TRACEBACK_HEADER` | Low | High | **P1** |
| 7 | Re-raise annotation | Detect bare `raise` in source line | Low | Medium | P3 |
| 8 | Doctest format | Strip framing, parse embedded traceback | Low | Low | P3 |
| 9 | pytest short traceback | No change needed (full traceback works) | None | None | — |
| 10 | LLM API Error JSON | New `APIErrorParser` | Low | Medium | **P1** |
| 11 | MCP JSON-RPC Error | New `MCPRpcParser` | Low | Medium | P2 |
| 12 | LangChain Agent verbose | New `AgentLogParser` | Medium | High | P2 |
| 13 | Token/Context limit | New `LLMErrorParser` | Low | High | **P1** |
| 14 | Agent tool truncated | Extend `AgentLogParser` | Low | High | P2 |
| 15 | SSE streaming errors | Extend `APIErrorParser` | Low | Medium | P2 |
| 16 | Image / Vision API errors | Handled by §10 | None | Medium | P3 |
| 17 | Google Gemini API errors | Extend `APIErrorParser` or new `GeminiErrorParser` | Low | Medium | **P1** |
| 18 | A2A protocol errors | Extend `MCPRpcParser` with A2A codes | Low | Medium | **P1** |
| 19 | Content moderation / safety | Extend `APIErrorParser` with policy detection | Low | Medium | P2 |
| 20 | Tool calling / function calling | Extend `APIErrorParser` with tool-specific codes | Low | High | P2 |
| 21 | OpenAI Responses API | Extend SSE parser with `response.failed` envelope | Low | Medium | P2 |
| 22 | Agent framework errors | New `AgentFrameworkParser` | Medium | High | P2 |
| 23 | LiteLLM unified exceptions | Extend `APIErrorParser` with LiteLLM exception map | Low | Medium | P2 |
| 24 | Anthropic Extended Thinking | Handled by §10 | None | Low | P3 |
| 25 | Embedding API errors | Handled by §10 | None | Medium | P3 |
| 26 | Batch API errors | Extend `APIErrorParser` with batch envelope | Low | Low | P3 |
| 27 | Realtime API WebSocket | Extend `APIErrorParser` with WebSocket messages | Low | Low | P3 |
| 28 | Audio API (Whisper/TTS) | Handled by §10 | None | Medium | P3 |
| 29 | Document / PDF input | Handled by §10 / §17 | None | Medium | P3 |
| 30 | Gemini multi-modal (video/audio) | Handled by §17 | None | Medium | P3 |
| 31 | Image generation (DALL-E/Imagen) | Handled by §10 / §17 | None | Medium | P3 |
| 32 | Video understanding | Handled by §17 | None | Low | P3 |
| 33 | Multi-modal token counting | Extend §13 `LLMErrorParser` | Low | Medium | P3 |

### Implementation Order (Recommended)

**Phase 1 — High Impact (P1):**
1. SyntaxError caret — most common Python format gap
2. Logging exc_info prefix — most common production log format
3. LLM API Error JSON — most common LLM format gap
4. Token/Context limit — high frequency, high reproduction value
5. Google Gemini API — third-largest provider, distinct format
6. A2A protocol — emerging standard alongside MCP
7. ExceptionGroup — growing with asyncio adoption

**Phase 2 — Agent/MCP Ecosystem (P2):**
8. LangChain Agent verbose + Agent tool truncated (combined parser)
9. Agent framework errors (CrewAI/AutoGen/ADK/Semantic Kernel)
10. Tool calling / function calling errors
11. MCP JSON-RPC Error + A2A protocol (shared parser)
12. Content moderation / safety filter errors
13. LiteLLM unified exception system
14. OpenAI Responses API errors
15. Exception notes
16. SSE streaming errors

**Phase 3 — Multi-Modal & Nice to Have (P3):**
17. Image / Vision API errors (free with §10)
18. Audio API errors (free with §10)
19. Document / PDF input errors (free with §10 / §17)
20. Gemini multi-modal errors (free with §17)
21. Image generation errors (free with §10 / §17)
22. Video understanding errors (free with §17)
23. Multi-modal token counting (extend §13)
24. Embedding API errors (free with §10)
25. Anthropic Extended Thinking (free with §10)
26. Batch API errors
27. Realtime API WebSocket errors
22. RecursionError depth
23. Warning format
24. Re-raise annotation
25. Doctest format
