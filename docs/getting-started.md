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

### LLM Providers

log2repro uses [litellm](https://github.com/BerriAI/litellm) — set the model via `--model` and configure the corresponding environment variables. litellm routes automatically based on the model prefix.

#### Cloud Providers

| Provider | Model Prefix | API Key | Base URL (optional) |
|----------|-------------|---------|---------------------|
| OpenAI | `gpt-4o`, `gpt-4o-mini` | `OPENAI_API_KEY` | `OPENAI_API_BASE` |
| Anthropic | `claude-3-opus`, `claude-3-sonnet` | `ANTHROPIC_API_KEY` | — |
| Azure OpenAI | `azure/gpt-4o` | `AZURE_API_KEY` | `AZURE_API_BASE` |
| DeepSeek | `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` | `DEEPSEEK_API_BASE` |
| DashScope (Qwen) | `dashscope/qwen-turbo` | `DASHSCOPE_API_KEY` | `DASHSCOPE_API_BASE` |
| Groq | `groq/llama3-70b-8192` | `GROQ_API_KEY` | `GROQ_API_BASE` |
| Mistral | `mistral/mistral-large` | `MISTRAL_API_KEY` | `MISTRAL_API_BASE` |
| OpenRouter | `openrouter/meta-llama/llama-3-70b` | `OPENROUTER_API_KEY` | `OPENROUTER_API_BASE` |
| Together AI | `together_ai/meta-llama/Llama-3-70b` | `TOGETHERAI_API_KEY` | — |

#### Local / Self-hosted

| Provider | Model Prefix | API Key | Base URL | Default |
|----------|-------------|---------|----------|---------|
| Ollama | `ollama/llama3` | `OLLAMA_API_KEY` | `OLLAMA_API_BASE` | `http://localhost:11434` |
| vLLM | `hosted_vllm/model-name` | `HOSTED_VLLM_API_KEY` | `HOSTED_VLLM_API_BASE` | — |
| SGLang | `openai/model-name` | `OPENAI_API_KEY` | `OPENAI_API_BASE` | `http://localhost:30000/v1` |
| LM Studio | `lm_studio/model-name` | `LM_STUDIO_API_KEY` | `LM_STUDIO_API_BASE` | — |
| Llamafile | `llamafile/model-name` | `LLAMAFILE_API_KEY` | `LLAMAFILE_API_BASE` | `http://127.0.0.1:8080/v1` |
| Xinference | `xinference/model-name` | `XINFERENCE_API_KEY` | `XINFERENCE_API_BASE` | — |

> **Note:** For locally deployed models with authentication enabled (common in enterprise environments), set the corresponding API key. If no authentication is configured, these can be omitted — litellm will use a placeholder value automatically.

#### Examples

```bash
# OpenAI
export OPENAI_API_KEY="sk-..."
log2repro run error.log --model gpt-4o

# Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."
log2repro run error.log --model claude-3-sonnet

# Ollama (local, no API key needed)
log2repro run error.log --model ollama/llama3

# Ollama on a remote server
export OLLAMA_API_BASE="http://192.168.1.100:11434"
log2repro run error.log --model ollama/llama3

# vLLM
export VLLM_API_BASE="http://localhost:8000/v1"
log2repro run error.log --model vllm/Qwen/Qwen2.5-7B-Instruct

# SGLang (uses OpenAI-compatible API)
export OPENAI_API_BASE="http://localhost:30000/v1"
log2repro run error.log --model openai/Qwen/Qwen2.5-7B-Instruct

# DeepSeek
export DEEPSEEK_API_KEY="sk-..."
log2repro run error.log --model deepseek/deepseek-chat

# Groq
export GROQ_API_KEY="gsk_..."
log2repro run error.log --model groq/llama3-70b-8192

# LM Studio (local)
export LM_STUDIO_API_BASE="http://localhost:1234/v1"
log2repro run error.log --model lm_studio/local-model

# Enterprise Ollama with API key
export OLLAMA_API_BASE="http://ollama.internal:11434"
export OLLAMA_API_KEY="sk-..."
log2repro run error.log --model ollama/llama3

# Enterprise vLLM with API key
export HOSTED_VLLM_API_BASE="http://vllm.internal:8000/v1"
export HOSTED_VLLM_API_KEY="sk-..."
log2repro run error.log --model hosted_vllm/Qwen/Qwen2.5-7B-Instruct
```

> **Tip:** For local providers (Ollama, vLLM, SGLang, LM Studio), ensure the model server is running before invoking log2repro.

### Sandbox timeout

```bash
log2repro run error.log --sandbox-timeout 20
```

### Refinement rounds

```bash
log2repro run error.log --max-refine 3
```

## Advanced Examples

### CI/CD Integration (GitHub Actions)

Automatically generate reproduction scripts when tests fail in CI:

```yaml
# .github/workflows/repro-on-failure.yml
name: Generate Repro on Failure
on:
  workflow_run:
    workflows: ["Tests"]
    types: [completed]

jobs:
  generate-repro:
    if: ${{ github.event.workflow_run.conclusion == 'failure' }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync

      - name: Download failed logs
        uses: actions/download-artifact@v4
        with:
          name: test-logs
          path: ./logs

      - name: Generate reproduction
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          for log in ./logs/*.txt; do
            echo "Processing $log..."
            uv run log2repro run "$log" \
              --output-dir "./repro_out/$(basename "$log" .txt)" \
              --model gpt-4o-mini \
              --sandbox-timeout 30 || true
          done

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: reproduction-scripts
          path: repro_out/
```

### Process Docker / journalctl Logs

Pipe logs from container runtimes or system journals:

```bash
# From Docker container
docker logs my-app 2>&1 | tail -50 | log2repro run - --output-dir ./repro_out

# From docker-compose
docker-compose logs my-app 2>&1 | log2repro run - --output-dir ./repro_out

# From journalctl
journalctl -u my-service --since "1 hour ago" --no-pager | log2repro run - --output-dir ./repro_out

# From Kubernetes pod
kubectl logs my-pod --tail=100 | log2repro run - --output-dir ./repro_out
```

### Sentry JSON Payload

Process a Sentry event directly:

```bash
# Export from Sentry API
curl -s "https://sentry.io/api/0/issues/$ISSUE_ID/events/latest/" \
  -H "Authorization: Bearer $SENTRY_TOKEN" | \
  log2repro run - --output-dir ./repro_out

# From a saved JSON file
log2repro run sentry_event.json --output-dir ./repro_out
```

### Python API (Programmatic Usage)

Use log2repro as a library:

```python
from pathlib import Path
from log2repro.parsers.stacktrace import StacktraceParser
from log2repro.generators.code_gen import ReproContext, generate_repro_script
from log2repro.extractors.ast_parser import extract_ast_context_from_source

# Parse
parser = StacktraceParser()
traces = parser.parse(Path("error.log").read_text())
trace = traces[0]

# Extract AST context (optional, improves quality)
ast_ctx = extract_ast_context_from_source(
    source=Path(trace.file).read_text(),
    filename=trace.file,
    target_line=trace.line,
    target_func=trace.chain[-1].split(":")[1] if trace.chain else "",
)

# Generate
ctx = ReproContext(trace=trace, ast_context=ast_ctx, model="gpt-4o")
files = generate_repro_script(ctx, sandbox_timeout=15, max_refine_rounds=3)

# Write output
out = Path("./repro_out")
out.mkdir(exist_ok=True)
for name, content in files.items():
    (out / name).write_text(content)
    print(f"Written: {name}")
```

### Root Cause Analysis (Python API)

```python
from log2repro import analyze

result = analyze(Path("error.log").read_text(), model="gpt-4o")
print(f"Root cause: {result.root_cause}")
print(f"Error type: {result.error_type}")
for rec in result.recommendations:
    print(f"  [{rec.confidence.upper()}] {rec.description}")
```

### Batch Processing Multiple Logs

```bash
# Process all .log files in a directory
for f in ./crash_logs/*.log; do
  name=$(basename "$f" .log)
  echo "=== Processing: $name ==="
  log2repro run "$f" \
    --output-dir "./repro_out/$name" \
    --model gpt-4o-mini \
    --max-refine 1 \
    --sandbox-timeout 20 || echo "Failed: $name"
done
```

### Model Comparison

Generate the same error with different models and compare quality:

```bash
# Compare GPT-4o vs Claude vs local model
for model in gpt-4o claude-3-sonnet ollama/llama3; do
  echo "=== Model: $model ==="
  log2repro run error.log \
    --output-dir "./repro_out/$model" \
    --model "$model" \
    --max-refine 2
done
```

### Evaluation and Benchmarking

Evaluate generated scripts programmatically:

```python
from log2repro.eval_metrics import evaluate_batch, GenerationInput
from pathlib import Path

inputs = []
for trace_dir in Path("./repro_out").iterdir():
    if trace_dir.is_dir():
        files = {f.name: f.read_text() for f in trace_dir.iterdir() if f.is_file()}
        inputs.append(GenerationInput(
            trace_name=trace_dir.name,
            files=files,
            tokens_used=3000,  # track from your LLM provider
            expected_error="ValueError: ...",  # from original trace
        ))

batch = evaluate_batch(inputs, sandbox_timeout=15)
print(batch.report())
```

### Verbose Mode for Debugging

When things go wrong, use verbose mode to see the full pipeline:

```bash
log2repro run error.log --verbose --output-dir ./repro_out
```

This shows:
- Parsed trace details
- LLM call attempts and retries
- Sandbox execution output
- Auto-fix classification and rounds

### Dry-run: Inspect What Gets Sent to the LLM

Before spending tokens, check what context log2repro extracts:

```bash
log2repro run error.log --dry-run
```

Output is JSON showing exactly what would be sent to the LLM:
- Parsed trace (file, line, error, chain, variables)
- AST context (signature, imports, variables)
- Selected model

## FAQ

**Q: The generated script doesn't reproduce the error?**

Try increasing `--max-refine` or check `README_repro.md` for repair suggestions.

**Q: Can I use it with non-Python errors?**

Currently only Python tracebacks are fully supported. Sentry JSON and CI logs are partially supported. See [Parser Reference](parser-reference.md).

**Q: Is my code sent to an LLM?**

Yes, the traceback, function signatures, imports, and variable names are sent to the LLM. Source file contents are NOT sent. Use `--dry-run` to see what would be sent.

**Q: How much does it cost?**

Typical generation uses ~2,000-4,000 tokens. With sandbox refinement, ~6,000-10,000 tokens total.
