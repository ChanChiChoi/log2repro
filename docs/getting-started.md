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
| Ollama | `ollama/llama3` | not required | `OLLAMA_API_BASE` | `http://localhost:11434` |
| vLLM | `vllm/model-name` | `VLLM_API_KEY` (optional) | `VLLM_API_BASE` | — |
| SGLang | `openai/model-name` | not required | `OPENAI_API_BASE` | `http://localhost:30000/v1` |
| LM Studio | `lm_studio/model-name` | not required | `LM_STUDIO_API_BASE` | — |
| Llamafile | `llamafile/model-name` | not required | `LLAMAFILE_API_BASE` | `http://127.0.0.1:8080/v1` |
| Xinference | `xinference/model-name` | not required | `XINFERENCE_API_BASE` | — |

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

## FAQ

**Q: The generated script doesn't reproduce the error?**

Try increasing `--max-refine` or check `README_repro.md` for repair suggestions.

**Q: Can I use it with non-Python errors?**

Currently only Python tracebacks are fully supported. Sentry JSON and CI logs are partially supported. See [Parser Reference](parser-reference.md).

**Q: Is my code sent to an LLM?**

Yes, the traceback, function signatures, imports, and variable names are sent to the LLM. Source file contents are NOT sent. Use `--dry-run` to see what would be sent.

**Q: How much does it cost?**

Typical generation uses ~2,000-4,000 tokens. With sandbox refinement, ~6,000-10,000 tokens total.
