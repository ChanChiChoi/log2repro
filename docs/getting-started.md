# Getting Started

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

**Requirements:** Python >= 3.10

## Your First Reproduction Script

### 1. Prepare an error log

Create `error.log` with a Python traceback:

```
Traceback (most recent call last):
  File "/app/api/handler.py", line 42, in fetch_user
    user = db.query(User).filter_by(id=user_id).one()
sqlalchemy.exc.NoResultFound: No row was found for one()
```

### 2. Run log2repro

```bash
log2repro run error.log --output-dir ./repro_out
```

Output:

```
Parsed: sqlalchemy.exc.NoResultFound: No row was found for one() at /app/api/handler.py:42
Generating reproduction script...
Running sandbox verification with auto-fix...
  ✓ reproduce.py
  ✓ requirements.txt
  ✓ mock_data.json
  ✓ README_repro.md
```

### 3. Run the reproduction script

```bash
cd repro_out
pip install -r requirements.txt
python reproduce.py
```

The script should trigger the original `NoResultFound` error.

## Using stdin

```bash
cat error.log | log2repro run - --output-dir ./repro_out
```

## Pasting directly

```bash
log2repro run 'Traceback (most recent call last):
  File "app.py", line 10, in process
    result = api.fetch(user_id)
requests.exceptions.ConnectionError: Connection refused'
```

## Dry-run mode

Parse only, no LLM calls:

```bash
log2repro run error.log --dry-run
```

## Specifying a model

```bash
log2repro run error.log --model gpt-4o --output-dir ./repro_out
log2repro run error.log --model claude-3-opus --output-dir ./repro_out
log2repro run error.log --model ollama/llama3 --output-dir ./repro_out
```

log2repro uses [litellm](https://github.com/BerriAI/litellm), so any model supported by litellm works.

## Configuration

### LLM API Key

Set the appropriate environment variable for your provider:

```bash
# OpenAI
export OPENAI_API_KEY="sk-..."

# Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# Or use a .env file
```

### Sandbox timeout

```bash
log2repro run error.log --sandbox-timeout 20
```

### Refinement rounds

```bash
log2repro run error.log --max-refine 3
```

## FAQ

**Q: The generated script doesn't reproduce the error?**

Try increasing `--max-refine` or check `README_repro.md` for repair suggestions.

**Q: Can I use it with non-Python errors?**

Currently only Python tracebacks are fully supported. Sentry JSON and CI logs are partially supported. See [Parser Reference](parser-reference.md).

**Q: Is my code sent to an LLM?**

Yes, the traceback, function signatures, imports, and variable names are sent to the LLM. Source file contents are NOT sent. Use `--dry-run` to see what would be sent.

**Q: How much does it cost?**

Typical generation uses ~2,000-4,000 tokens. With sandbox refinement, ~6,000-10,000 tokens total.
