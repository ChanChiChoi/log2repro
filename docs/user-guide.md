# User Guide

## CLI Reference

### `log2repro run`

Parse an error log and generate a runnable reproduction script.

```bash
log2repro run <input> [OPTIONS]
```

#### Arguments

| Argument | Description |
|----------|-------------|
| `input` | File path, `"-"` for stdin, or raw traceback text |

#### Options

| Flag | Default | Description |
|------|---------|-------------|
| `-m`, `--model` | `gpt-4o` | LLM model identifier |
| `-n`, `--dry-run` | `false` | Parse only, skip LLM and sandbox |
| `-d`, `--output-dir` | `./repro_out` | Output directory |
| `-o`, `--output` | - | Write JSON to file (legacy mode) |
| `--sandbox-timeout` | `10` | Max seconds for sandbox execution |
| `--max-refine` | `2` | Max sandbox→LLM refinement rounds |
| `-v`, `--verbose` | `false` | Enable verbose logging |

### `log2repro version`

Print the version string.

## Input Formats

### Python Traceback (primary)

```
Traceback (most recent call last):
  File "/app/models/user.py", line 85, in validate_email
    if "@" not in email:
TypeError: argument of type 'NoneType' is not iterable
```

### Chained Exceptions

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

### Sentry JSON

```json
{
  "exception": {
    "values": [{
      "type": "ValueError",
      "value": "invalid literal",
      "stacktrace": {
        "frames": [
          {"filename": "app.py", "lineno": 10, "function": "parse"}
        ]
      }
    }]
  }
}
```

### CI Logs

GitHub Actions, GitLab CI, or any log with ANSI escape codes. log2repro strips ANSI codes automatically and delegates to the traceback parser.

## Output Structure

```
repro_out/
├── reproduce.py        # Minimal reproduction script
├── requirements.txt    # pip dependencies
├── mock_data.json      # Mock data loaded by the script
└── README_repro.md     # Usage instructions + auto-fix history
```

### reproduce.py

A standalone Python script that:
- Triggers the original error when run with `python reproduce.py`
- Uses `unittest.mock` for external calls (no real network/DB)
- Exits with non-zero code on the expected error

### requirements.txt

Pip dependencies needed by the reproduction script. Typically minimal (often just stdlib).

### mock_data.json

JSON fixture data loaded by the reproduction script. Contains test values that trigger the error.

### README_repro.md

Markdown file with:
- Original error information (file, line, error, call chain)
- Reproduction status (success/failure)
- Usage instructions
- Auto-fix history (if refinement was needed)
- Repair suggestions (if auto-fix failed)

## Model Selection

log2repro uses [litellm](https://github.com/BerriAI/litellm), supporting any compatible model:

```bash
# OpenAI
log2repro run error.log --model gpt-4o
log2repro run error.log --model gpt-4o-mini

# Anthropic
log2repro run error.log --model claude-3-opus
log2repro run error.log --model claude-3-sonnet

# Local (via Ollama)
log2repro run error.log --model ollama/llama3

# Azure OpenAI
log2repro run error.log --model azure/gpt-4o
```

Set the appropriate API key environment variable for your provider.

## Sandbox Tuning

### Timeout

Default 10 seconds. Increase for scripts that import heavy libraries:

```bash
log2repro run error.log --sandbox-timeout 30
```

### Refinement rounds

Default 2 rounds. Increase if the first generation often needs fixes:

```bash
log2repro run error.log --max-refine 4
```

Set to 0 to skip sandbox verification entirely:

```bash
log2repro run error.log --max-refine 0
```

## Dry-run Mode

Use `--dry-run` to inspect the parsed context without making LLM calls:

```bash
log2repro run error.log --dry-run
```

Output is a JSON object with:
- `traces`: Parsed trace information
- `ast_contexts`: Extracted AST context (if source files are accessible)
- `model`: Selected model
- `dry_run`: `true`

## Evaluation

Run quality metrics on generated scripts:

```python
from log2repro.eval_metrics import evaluate_batch, GenerationInput

inputs = [
    GenerationInput(
        trace_name="my_trace",
        files={"reproduce.py": "...", "requirements.txt": "...", "mock_data.json": "{}"},
        tokens_used=800,
        expected_error="ValueError: bad value",
    ),
]

batch = evaluate_batch(inputs)
print(batch.report())
```

See [Evaluation Guide](evaluation.md) for details.

## Troubleshooting

### "Could not extract any trace from the input"

The input doesn't contain a recognizable Python traceback. Check:
- Is it a Python traceback (starts with `Traceback (most recent call last):`)?
- For Sentry JSON, does it have `exception.values` or `stacktrace` fields?

### "LLM generation failed after N attempts"

- Check your API key is set correctly
- Check network connectivity to the LLM provider
- Try a different model with `--model`

### Generated script doesn't reproduce the error

- Check `README_repro.md` for auto-fix history and suggestions
- Try increasing `--max-refine`
- The error may require specific runtime conditions that can't be mocked

### Sandbox timeout

- Increase `--sandbox-timeout`
- Check if the script imports heavy libraries (numpy, torch, etc.)
