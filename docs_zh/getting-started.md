# 快速开始

## 安装

```bash
# 使用 uv（推荐）
uv pip install log2repro

# 使用 pip
pip install log2repro

# 从源码安装
git clone https://github.com/ChanChiChoi/log2repro.git
cd log2repro
uv sync
```

**环境要求：** Python >= 3.10

## 生成第一个复现脚本

### 1. 准备错误日志

创建 `error.log`，内容为一段 Python traceback：

```
Traceback (most recent call last):
  File "/app/api/handler.py", line 42, in fetch_user
    user = db.query(User).filter_by(id=user_id).one()
sqlalchemy.exc.NoResultFound: No row was found for one()
```

### 2. 运行 log2repro

```bash
log2repro run error.log --output-dir ./repro_out
```

输出：

```
Parsed: sqlalchemy.exc.NoResultFound: No row was found for one() at /app/api/handler.py:42
Generating reproduction script...
Running sandbox verification with auto-fix...
  ✓ reproduce.py
  ✓ requirements.txt
  ✓ mock_data.json
  ✓ README_repro.md
```

### 3. 运行复现脚本

```bash
cd repro_out
pip install -r requirements.txt
python reproduce.py
```

脚本应该会触发原始的 `NoResultFound` 错误。

## 从 stdin 读取

```bash
cat error.log | log2repro run - --output-dir ./repro_out
```

## 直接粘贴文本

```bash
log2repro run 'Traceback (most recent call last):
  File "app.py", line 10, in process
    result = api.fetch(user_id)
requests.exceptions.ConnectionError: Connection refused'
```

## 仅解析模式（dry-run）

只解析日志，不调用 LLM：

```bash
log2repro run error.log --dry-run
```

## 指定模型

```bash
log2repro run error.log --model gpt-4o --output-dir ./repro_out
log2repro run error.log --model claude-3-opus --output-dir ./repro_out
log2repro run error.log --model ollama/llama3 --output-dir ./repro_out
```

log2repro 使用 [litellm](https://github.com/BerriAI/litellm)，支持所有 litellm 兼容的模型。

## 配置

### LLM 提供商

log2repro 使用 [litellm](https://github.com/BerriAI/litellm)——通过 `--model` 指定模型，设置对应的环境变量即可。litellm 根据模型前缀自动路由到对应提供商。

#### 云端提供商

| 提供商 | 模型前缀 | API 密钥 | Base URL（可选） |
|--------|----------|----------|------------------|
| OpenAI | `gpt-4o`、`gpt-4o-mini` | `OPENAI_API_KEY` | `OPENAI_API_BASE` |
| Anthropic | `claude-3-opus`、`claude-3-sonnet` | `ANTHROPIC_API_KEY` | — |
| Azure OpenAI | `azure/gpt-4o` | `AZURE_API_KEY` | `AZURE_API_BASE` |
| DeepSeek | `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` | `DEEPSEEK_API_BASE` |
| DashScope（通义千问） | `dashscope/qwen-turbo` | `DASHSCOPE_API_KEY` | `DASHSCOPE_API_BASE` |
| Groq | `groq/llama3-70b-8192` | `GROQ_API_KEY` | `GROQ_API_BASE` |
| Mistral | `mistral/mistral-large` | `MISTRAL_API_KEY` | `MISTRAL_API_BASE` |
| OpenRouter | `openrouter/meta-llama/llama-3-70b` | `OPENROUTER_API_KEY` | `OPENROUTER_API_BASE` |
| Together AI | `together_ai/meta-llama/Llama-3-70b` | `TOGETHERAI_API_KEY` | — |

#### 本地 / 自托管

| 提供商 | 模型前缀 | API 密钥 | Base URL | 默认值 |
|--------|----------|----------|----------|--------|
| Ollama | `ollama/llama3` | `OLLAMA_API_KEY` | `OLLAMA_API_BASE` | `http://localhost:11434` |
| vLLM | `hosted_vllm/模型名` | `HOSTED_VLLM_API_KEY` | `HOSTED_VLLM_API_BASE` | — |
| SGLang | `openai/模型名` | `OPENAI_API_KEY` | `OPENAI_API_BASE` | `http://localhost:30000/v1` |
| LM Studio | `lm_studio/模型名` | `LM_STUDIO_API_KEY` | `LM_STUDIO_API_BASE` | — |
| Llamafile | `llamafile/模型名` | `LLAMAFILE_API_KEY` | `LLAMAFILE_API_BASE` | `http://127.0.0.1:8080/v1` |
| Xinference | `xinference/模型名` | `XINFERENCE_API_KEY` | `XINFERENCE_API_BASE` | — |

> **注意：** 企业内部部署的本地模型通常会启用 API 密钥认证，此时需要设置对应的 API 密钥环境变量。如果服务未配置认证，可以不设置——litellm 会自动使用占位值。

#### 示例

```bash
# OpenAI
export OPENAI_API_KEY="sk-..."
log2repro run error.log --model gpt-4o

# Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."
log2repro run error.log --model claude-3-sonnet

# Ollama（本地，无需 API 密钥）
log2repro run error.log --model ollama/llama3

# Ollama 远程服务器
export OLLAMA_API_BASE="http://192.168.1.100:11434"
log2repro run error.log --model ollama/llama3

# vLLM
export VLLM_API_BASE="http://localhost:8000/v1"
log2repro run error.log --model vllm/Qwen/Qwen2.5-7B-Instruct

# SGLang（使用 OpenAI 兼容 API）
export OPENAI_API_BASE="http://localhost:30000/v1"
log2repro run error.log --model openai/Qwen/Qwen2.5-7B-Instruct

# DeepSeek
export DEEPSEEK_API_KEY="sk-..."
log2repro run error.log --model deepseek/deepseek-chat

# Groq
export GROQ_API_KEY="gsk_..."
log2repro run error.log --model groq/llama3-70b-8192

# LM Studio（本地）
export LM_STUDIO_API_BASE="http://localhost:1234/v1"
log2repro run error.log --model lm_studio/local-model

# 企业内部 Ollama（带 API 密钥）
export OLLAMA_API_BASE="http://ollama.internal:11434"
export OLLAMA_API_KEY="sk-..."
log2repro run error.log --model ollama/llama3

# 企业内部 vLLM（带 API 密钥）
export HOSTED_VLLM_API_BASE="http://vllm.internal:8000/v1"
export HOSTED_VLLM_API_KEY="sk-..."
log2repro run error.log --model hosted_vllm/Qwen/Qwen2.5-7B-Instruct
```

> **提示：** 使用本地提供商（Ollama、vLLM、SGLang、LM Studio）时，请确保模型服务已在运行。

### 沙箱超时

```bash
log2repro run error.log --sandbox-timeout 20
```

### 修正轮次

```bash
log2repro run error.log --max-refine 3
```

## 高阶用法

### CI/CD 集成（GitHub Actions）

在 CI 中测试失败时自动生成复现脚本：

```yaml
# .github/workflows/repro-on-failure.yml
name: 失败时生成复现脚本
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

      - name: 下载失败日志
        uses: actions/download-artifact@v4
        with:
          name: test-logs
          path: ./logs

      - name: 生成复现脚本
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          for log in ./logs/*.txt; do
            echo "处理 $log..."
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

### 处理 Docker / journalctl 日志

从容器运行时或系统日志管道输入：

```bash
# 从 Docker 容器
docker logs my-app 2>&1 | tail -50 | log2repro run - --output-dir ./repro_out

# 从 docker-compose
docker-compose logs my-app 2>&1 | log2repro run - --output-dir ./repro_out

# 从 journalctl
journalctl -u my-service --since "1 hour ago" --no-pager | log2repro run - --output-dir ./repro_out

# 从 Kubernetes Pod
kubectl logs my-pod --tail=100 | log2repro run - --output-dir ./repro_out
```

### Sentry JSON 数据

直接处理 Sentry 事件：

```bash
# 从 Sentry API 导出
curl -s "https://sentry.io/api/0/issues/$ISSUE_ID/events/latest/" \
  -H "Authorization: Bearer $SENTRY_TOKEN" | \
  log2repro run - --output-dir ./repro_out

# 从已保存的 JSON 文件
log2repro run sentry_event.json --output-dir ./repro_out
```

### Python API（编程方式使用）

将 log2repro 作为库使用：

```python
from pathlib import Path
from log2repro.parsers.stacktrace import StacktraceParser
from log2repro.generators.code_gen import ReproContext, generate_repro_script
from log2repro.extractors.ast_parser import extract_ast_context_from_source

# 解析
parser = StacktraceParser()
traces = parser.parse(Path("error.log").read_text())
trace = traces[0]

# 提取 AST 上下文（可选，提升生成质量）
ast_ctx = extract_ast_context_from_source(
    source=Path(trace.file).read_text(),
    filename=trace.file,
    target_line=trace.line,
    target_func=trace.chain[-1].split(":")[1] if trace.chain else "",
)

# 生成
ctx = ReproContext(trace=trace, ast_context=ast_ctx, model="gpt-4o")
files = generate_repro_script(ctx, sandbox_timeout=15, max_refine_rounds=3)

# 写入输出
out = Path("./repro_out")
out.mkdir(exist_ok=True)
for name, content in files.items():
    (out / name).write_text(content)
    print(f"已写入: {name}")
```

### 批量处理多个日志

```bash
# 处理目录下所有 .log 文件
for f in ./crash_logs/*.log; do
  name=$(basename "$f" .log)
  echo "=== 处理: $name ==="
  log2repro run "$f" \
    --output-dir "./repro_out/$name" \
    --model gpt-4o-mini \
    --max-refine 1 \
    --sandbox-timeout 20 || echo "失败: $name"
done
```

### 模型对比

用不同模型生成同一个错误的复现脚本，对比质量：

```bash
# 对比 GPT-4o vs Claude vs 本地模型
for model in gpt-4o claude-3-sonnet ollama/llama3; do
  echo "=== 模型: $model ==="
  log2repro run error.log \
    --output-dir "./repro_out/$model" \
    --model "$model" \
    --max-refine 2
done
```

### 评估与基准测试

以编程方式评估生成的脚本：

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
            tokens_used=3000,  # 从你的 LLM 提供商获取
            expected_error="ValueError: ...",  # 来自原始 trace
        ))

batch = evaluate_batch(inputs, sandbox_timeout=15)
print(batch.report())
```

### 详细模式（调试用）

当出现问题时，使用详细模式查看完整流水线：

```bash
log2repro run error.log --verbose --output-dir ./repro_out
```

输出包括：
- 解析的 trace 详情
- LLM 调用尝试和重试
- 沙箱执行输出
- 自动修复分类和轮次

### Dry-run：检查发送给 LLM 的内容

在消耗 token 之前，先检查 log2repro 提取了哪些上下文：

```bash
log2repro run error.log --dry-run
```

输出为 JSON，精确展示将发送给 LLM 的内容：
- 解析的 trace（文件、行号、错误、调用链、变量）
- AST 上下文（签名、import、变量）
- 选择的模型

## 常见问题

**Q: 生成的脚本没有复现错误？**

尝试增加 `--max-refine`，或查看 `README_repro.md` 中的修复建议。

**Q: 能否用于非 Python 错误？**

目前仅完全支持 Python traceback。Sentry JSON 和 CI 日志部分支持。详见 [解析器参考](parser-reference.md)。

**Q: 我的代码会被发送到 LLM 吗？**

会。traceback、函数签名、import 语句和变量名会发送给 LLM，但**不会**发送源文件完整内容。使用 `--dry-run` 可以预览将发送的内容。

**Q: 费用是多少？**

单次生成约消耗 2,000-4,000 tokens。包含沙箱修正约 6,000-10,000 tokens。
