# 用户指南

## CLI 参考

### `log2repro run`

解析错误日志并生成可运行的复现脚本。

```bash
log2repro run <input> [OPTIONS]
```

#### 参数

| 参数 | 说明 |
|------|------|
| `input` | 文件路径、`"-"` 表示 stdin，或原始 traceback 文本 |

#### 选项

| 标志 | 默认值 | 说明 |
|------|--------|------|
| `-m`, `--model` | `gpt-4o` | LLM 模型标识 |
| `-n`, `--dry-run` | `false` | 仅解析，跳过 LLM 和沙箱 |
| `-a`, `--analyze` | `false` | 开启根因分析（输出 `analysis.md`） |
| `-d`, `--output-dir` | `./repro_out` | 输出目录 |
| `-o`, `--output` | - | 将 JSON 写入文件（旧模式） |
| `--sandbox-timeout` | `10` | 沙箱执行最大秒数 |
| `--max-refine` | `2` | 沙箱→LLM 最大修正轮次 |
| `--extra-body` | - | 传给 LLM API 的额外 JSON 参数（如 `{"enable_thinking": false}`） |
| `-v`, `--verbose` | `false` | 启用详细日志 |

### `log2repro version`

打印版本号。

## 输入格式

### Python Traceback（主要格式）

```
Traceback (most recent call last):
  File "/app/models/user.py", line 85, in validate_email
    if "@" not in email:
TypeError: argument of type 'NoneType' is not iterable
```

### 链式异常

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

### CI 日志

GitHub Actions、GitLab CI 或任何包含 ANSI 转义码的日志。log2repro 会自动剥离 ANSI 码并委托给 traceback 解析器。

## 输出结构

```
repro_out/
├── reproduce.py        # 最小复现脚本
├── requirements.txt    # pip 依赖
├── mock_data.json      # 脚本加载的 mock 数据
└── README_repro.md     # 使用说明 + 自动修复历史
```

### reproduce.py

一个独立的 Python 脚本：
- 运行 `python reproduce.py` 时触发原始错误
- 使用 `unittest.mock` 处理外部调用（无真实网络/数据库）
- 在预期错误时以非零退出码退出

### requirements.txt

复现脚本所需的 pip 依赖。通常很少（往往只有标准库）。

### mock_data.json

复现脚本加载的 JSON 夹具数据，包含触发错误的测试值。

### README_repro.md

Markdown 文件，包含：
- 原始错误信息（文件、行号、错误、调用链）
- 复现状态（成功/失败）
- 使用说明
- 自动修复历史（如果进行了修正）
- 修复建议（如果自动修复失败）

## 模型选择

log2repro 使用 [litellm](https://github.com/BerriAI/litellm)，支持所有兼容模型：

```bash
# OpenAI
log2repro run error.log --model gpt-4o
log2repro run error.log --model gpt-4o-mini

# Anthropic
log2repro run error.log --model claude-3-opus
log2repro run error.log --model claude-3-sonnet

# 本地模型（通过 Ollama）
log2repro run error.log --model ollama/llama3

# Azure OpenAI
log2repro run error.log --model azure/gpt-4o
```

设置对应提供商的 API 密钥环境变量即可。

## 思考模型

部分模型（如 Qwen3、DeepSeek-R1）具有"思考"或"推理"模式，会将思维链返回到单独的字段中。log2repro 会自动处理这种情况：

- 如果模型在 `content` 中返回答案，直接使用。
- 如果 `content` 为 `None` 但 `reasoning_content` 存在，log2repro 会回退使用 `reasoning_content`。
- 使用 `--verbose` 时，思考内容会自动打印。

建议关闭思考模式以获得直接的代码生成结果：

```bash
# Qwen3：关闭思考
log2repro run error.log --model hosted_vllm/Qwen3.5-27B \
  --extra-body '{"enable_thinking": false}'

# DeepSeek-R1：关闭思考
log2repro run error.log --model deepseek/deepseek-reasoner \
  --extra-body '{"enable_thinking": false}'
```

`--extra-body` 参数接受任意 JSON 对象，直接传递给 LLM API 请求体。适用于 litellm 标准选项未覆盖的提供商特定参数。

## 沙箱调参

### 超时

默认 10 秒。如果脚本导入了重量级库，可增加超时：

```bash
log2repro run error.log --sandbox-timeout 30
```

### 修正轮次

默认 2 轮。如果首次生成经常需要修复，可增加轮次：

```bash
log2repro run error.log --max-refine 4
```

设为 0 可跳过沙箱验证：

```bash
log2repro run error.log --max-refine 0
```

## 仅解析模式（dry-run）

使用 `--dry-run` 可以检查解析后的上下文，而不调用 LLM：

```bash
log2repro run error.log --dry-run
```

输出为 JSON 对象，包含：
- `traces`：解析的 trace 信息
- `ast_contexts`：提取的 AST 上下文（如果源文件可访问）
- `model`：选择的模型
- `dry_run`：`true`

## 评估

对生成的脚本运行质量指标：

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

详见 [评估指南](evaluation.md)。

## 故障排查

### "Could not extract any trace from the input"

输入中没有可识别的 Python traceback。检查：
- 是否为 Python traceback（以 `Traceback (most recent call last):` 开头）？
- Sentry JSON 是否包含 `exception.values` 或 `stacktrace` 字段？

### "LLM generation failed after N attempts"

- 检查 API 密钥是否正确设置
- 检查与 LLM 提供商的网络连接
- 尝试使用 `--model` 切换模型

### 生成的脚本没有复现错误

- 查看 `README_repro.md` 中的自动修复历史和建议
- 尝试增加 `--max-refine`
- 错误可能需要特定的运行时条件，无法通过 mock 实现

### 沙箱超时

- 增加 `--sandbox-timeout`
- 检查脚本是否导入了重量级库（numpy、torch 等）
