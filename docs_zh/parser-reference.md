# 解析器参考

## 概述

log2repro 支持三种输入格式，每种由专用解析器处理。CLI 自动检测格式并路由到相应解析器。

| 解析器 | 类 | 格式 | 状态 |
|--------|-----|------|------|
| Stacktrace | `StacktraceParser` | Python traceback 文本 | 完整支持 |
| Sentry | `SentryParser` | Sentry JSON 数据 | 完整支持 |
| CI 日志 | `CILogParser` | 含 ANSI 码的 CI 输出 | 完整支持 |

## Python Traceback 解析器

### 识别的模式

**Traceback 头：**
```
Traceback (most recent call last):
```

**调用点：**
```
  File "path/to/file.py", line 42, in function_name
```

**异常行（两种形式）：**
```
# 带点号的模块路径
ssl.SSLCertVerificationError: certificate verify failed

# 裸异常名（必须包含至少一个小写字母）
ValueError: bad value
```

### 链式异常

log2repro 处理 Python 的异常链式语法：

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

链中的每个 traceback 都会被独立解析，返回为单独的 `ParsedTrace`。

### 上下文变量提取

解析器从 traceback 中显示的源码行提取变量名：

```
  File "app.py", line 10, in process
    result = api.fetch(user_id)
```

提取的变量：`result`、`api`、`fetch`、`user_id`

**排除规则：**
- Python 关键字（`if`、`for`、`return` 等）
- 内置函数（`print`、`len`、`range` 等）
- 单字符名称
- 调用点行中的词（`File`、`line`、`in`）

### 边界情况

| 情况 | 示例 | 处理方式 |
|------|------|----------|
| 下划线前缀类型 | `_UFuncNoLoopError` | 正则允许 `_` 前缀 |
| 全大写短名称 | `OSError` | 要求至少一个小写字母 |
| 带点号的模块路径 | `ssl.SSLCertVerificationError` | 匹配完整点号前缀 |
| 无消息 | `KeyError`（无冒号） | 消息默认为空字符串 |
| 深层嵌套链 | 3+ 链式异常 | 每个独立解析 |

### 已知限制

- **非 Python traceback：** 不支持 Java、JavaScript、Go 堆栈跟踪
- **严重修改的格式：** 某些日志框架会重新格式化 traceback，导致正则匹配失败
- **C 扩展帧：** 来自 `.so` 文件的帧可能有非标准格式

## Sentry JSON 解析器

### 输入格式

包含异常数据的标准 Sentry 事件 JSON：

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

### 字段映射

| Sentry 字段 | ParsedTrace 字段 | 说明 |
|-------------|------------------|------|
| `exception.values[].type` | `error`（类型部分） | 与 `value` 合并 |
| `exception.values[].value` | `error`（消息部分） | 与 `type` 合并 |
| `stacktrace.frames[-1].filename` | `file` | 最后一帧 = 错误源头 |
| `stacktrace.frames[-1].lineno` | `line` | 最后一帧 = 错误源头 |
| `stacktrace.frames[*]` | `chain` | 所有帧作为调用链 |
| `stacktrace.frames[*].vars` | `context_vars` | 所有帧的变量名 |

### 回退路径

解析器尝试多条路径查找异常数据：

1. `exception.values[0]` — 标准 Sentry 格式
2. 顶层 `stacktrace` — 旧版 Sentry 格式
3. `culprit` 字段 — 最小回退

### 示例

```python
from log2repro.parsers.sentry import SentryParser

parser = SentryParser()
traces = parser.parse(sentry_json_string)
# traces[0].error == "ValueError: invalid literal for int()"
# traces[0].file == "utils.py"
# traces[0].line == 25
```

## CI 日志解析器

### 工作原理

1. **剥离 ANSI 码** — 移除 `\x1b[...m` 转义序列
2. **尝试完整解析** — 将清理后的文本委托给 `StacktraceParser`
3. **分段回退** — 如果完整解析失败，按 CI 步骤边界分割，逐段解析

### CI 步骤边界

解析器识别以下模式作为分段边界：

| 模式 | 示例 |
|------|------|
| `##[` | `##[error]Process completed with exit code 1` |
| `Run ` | `Run pytest --tb=short` |
| `Step ` | `Step 3/5: Run tests` |
| `ERROR` | `ERROR: test failed` |
| `FAIL` | `FAIL: test_parse_input` |

### 示例

```
\x1b[32mINFO\x1b[0m: Running tests...
\x1b[31mERROR\x1b[0m: Traceback (most recent call last):
  File "test_app.py", line 15, in test_parse
    assert parse("abc") == 42
AssertionError: assert None == 42
```

剥离 ANSI 后，traceback 被正常解析。

### ANSI 码支持

解析器剥离所有标准 ANSI 转义序列：
- SGR：`\x1b[...m`（颜色、加粗等）
- 光标：`\x1b[...A/B/C/D`（移动）
- 擦除：`\x1b[...J/K`（清除屏幕/行）
- OSC：`\x1b]...\x07`（窗口标题等）

## 解析器选择

### 自动检测

CLI 使用以下优先级：

1. **Sentry JSON：** 文本以 `{` 开头且包含 `"exception"` 或 `"stacktrace"`
2. **CI 日志：** 包含 ANSI 转义码
3. **Stacktrace：** 包含 `Traceback (most recent call last):`
4. **原始文本：** 回退到 stacktrace 解析器（可能返回空列表）

### 手动选择（API）

```python
from log2repro.parsers.stacktrace import StacktraceParser
from log2repro.parsers.sentry import SentryParser
from log2repro.parsers.ci_log import CILogParser

# 直接使用特定解析器
parser = StacktraceParser()
traces = parser.parse(text)
```

## ParsedTrace 模型

所有解析器都产生 `ParsedTrace` 对象：

```python
class ParsedTrace(BaseModel):
    file: str          # 源文件路径
    line: int          # 行号（>= 0）
    error: str         # "ErrorType: message"
    context_vars: list[str]  # 源码行中的变量名
    chain: list[str]   # 调用链 ["file:func:line", ...]
```

### 链格式

`chain` 中的每个条目遵循格式：`文件名:函数名:行号`

```python
# 链示例
["middleware.py:process_request:45", "app.py:handle:12", "app.py:main:5"]
```

最后一个是错误源头；第一个是最外层调用。
