# Parser Reference

## Overview

log2repro supports three input formats, each handled by a dedicated parser. The CLI auto-detects the format and routes to the appropriate parser.

| Parser | Class | Format | Status |
|--------|-------|--------|--------|
| Stacktrace | `StacktraceParser` | Python traceback text | Full support |
| Sentry | `SentryParser` | Sentry JSON payload | Full support |
| CI Log | `CILogParser` | CI output with ANSI codes | Full support |

## Python Traceback Parser

### Recognized Patterns

**Traceback header:**
```
Traceback (most recent call last):
```

**Call site:**
```
  File "path/to/file.py", line 42, in function_name
```

**Exception line (two forms):**
```
# Dotted module path
ssl.SSLCertVerificationError: certificate verify failed

# Bare exception name (must contain at least one lowercase letter)
ValueError: bad value
```

### Chained Exceptions

log2repro handles Python's exception chaining syntax:

```
Traceback (most recent call last):
  File "decoder.py", line 67, in decode_frame
    header = struct.unpack('!IHH', data[:8])
struct.error: unpack requires a buffer of 8 bytes

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "handler.py", line 134, in on_data
    frame = self._decoder.decode_frame(chunk)
ProtocolError: Truncated frame
```

Each traceback in the chain is parsed independently and returned as a separate `ParsedTrace`.

### Context Variable Extraction

The parser extracts variable names from source lines shown in the traceback:

```
  File "app.py", line 10, in process
    result = api.fetch(user_id)
```

Extracted variables: `result`, `api`, `fetch`, `user_id`

**Exclusion rules:**
- Python keywords (`if`, `for`, `return`, etc.)
- Built-in functions (`print`, `len`, `range`, etc.)
- Single-character names
- Words from call site lines (`File`, `line`, `in`)

### Edge Cases

| Case | Example | Handling |
|------|---------|----------|
| Underscore-prefixed types | `_UFuncNoLoopError` | Regex allows `_` prefix |
| All-caps short names | `OSError` | Requires at least one lowercase letter |
| Dotted module paths | `ssl.SSLCertVerificationError` | Full dotted prefix matched |
| No message | `KeyError` (no colon) | Message defaults to empty string |
| Deeply nested chains | 3+ chained exceptions | Each parsed independently |

### Known Limitations

- **Non-Python tracebacks**: Java, JavaScript, Go stack traces are not supported
- **Heavily modified formatting**: Some logging frameworks reformat tracebacks in ways that break the regex
- **C extension frames**: Frames from `.so` files may have non-standard formatting

## Sentry JSON Parser

### Input Format

Standard Sentry event JSON with exception data:

```json
{
  "exception": {
    "values": [{
      "type": "ValueError",
      "value": "invalid literal for int()",
      "stacktrace": {
        "frames": [
          {
            "filename": "app.py",
            "lineno": 10,
            "function": "parse_input",
            "vars": {"raw": "abc", "base": 10}
          },
          {
            "filename": "utils.py",
            "lineno": 25,
            "function": "safe_int",
            "vars": {"value": "abc"}
          }
        ]
      }
    }]
  }
}
```

### Field Mapping

| Sentry Field | ParsedTrace Field | Notes |
|--------------|-------------------|-------|
| `exception.values[].type` | `error` (type part) | Combined with `value` |
| `exception.values[].value` | `error` (message part) | Combined with `type` |
| `stacktrace.frames[-1].filename` | `file` | Last frame = error origin |
| `stacktrace.frames[-1].lineno` | `line` | Last frame = error origin |
| `stacktrace.frames[*]` | `chain` | All frames as call chain |
| `stacktrace.frames[*].vars` | `context_vars` | Variable names from all frames |

### Fallback Paths

The parser tries multiple paths to find exception data:

1. `exception.values[0]` — standard Sentry format
2. Top-level `stacktrace` — older Sentry format
3. `culprit` field — minimal fallback

### Example

```python
from log2repro.parsers.sentry import SentryParser

parser = SentryParser()
traces = parser.parse(sentry_json_string)
# traces[0].error == "ValueError: invalid literal for int()"
# traces[0].file == "utils.py"
# traces[0].line == 25
```

## CI Log Parser

### How It Works

1. **Strip ANSI codes** — removes `\x1b[...m` escape sequences
2. **Try full parse** — delegates to `StacktraceParser` on cleaned text
3. **Segment fallback** — if full parse fails, splits by CI step boundaries and parses each segment

### CI Step Boundaries

The parser recognizes these patterns as segment boundaries:

| Pattern | Example |
|---------|---------|
| `##[` | `##[error]Process completed with exit code 1` |
| `Run ` | `Run pytest --tb=short` |
| `Step ` | `Step 3/5: Run tests` |
| `ERROR` | `ERROR: test failed` |
| `FAIL` | `FAIL: test_parse_input` |

### Example

```
\x1b[32mINFO\x1b[0m: Running tests...
\x1b[31mERROR\x1b[0m: Traceback (most recent call last):
  File "test_app.py", line 15, in test_parse
    assert parse("abc") == 42
AssertionError: assert None == 42
```

After ANSI stripping, the traceback is extracted and parsed normally.

### ANSI Code Support

The parser strips all standard ANSI escape sequences:
- SGR: `\x1b[...m` (colors, bold, etc.)
- Cursor: `\x1b[...A/B/C/D` (movement)
- Erase: `\x1b[...J/K` (clear screen/line)
- OSC: `\x1b]...\x07` (window title, etc.)

## Parser Selection

### Auto-Detection

The CLI uses this priority order:

1. **Sentry JSON**: Text starts with `{` and contains `"exception"` or `"stacktrace"`
2. **CI Log**: Contains ANSI escape codes
3. **Stacktrace**: Contains `Traceback (most recent call last):`
4. **Raw text**: Falls back to stacktrace parser (may return empty list)

### Manual Selection (API)

```python
from log2repro.parsers.stacktrace import StacktraceParser
from log2repro.parsers.sentry import SentryParser
from log2repro.parsers.ci_log import CILogParser

# Use specific parser directly
parser = StacktraceParser()
traces = parser.parse(text)
```

## ParsedTrace Model

All parsers produce `ParsedTrace` objects:

```python
class ParsedTrace(BaseModel):
    file: str          # Source file path
    line: int          # Line number (>= 0)
    error: str         # "ErrorType: message"
    context_vars: list[str]  # Variable names from source lines
    chain: list[str]   # Call chain ["file:func:line", ...]
```

### Chain Format

Each entry in `chain` follows the format: `filename:function_name:line_number`

```python
# Example chain
["middleware.py:process_request:45", "app.py:handle:12", "app.py:main:5"]
```

The last entry is the error origin; the first is the outermost call.
