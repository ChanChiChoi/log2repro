# Python 错误格式 Gap — 详细参考

> 本文档详细描述 log2repro 尚未支持的 Python 错误格式。每个章节包含真实示例、根因分析和实现说明。对应 [路线图 D9](roadmap.md)。

---

## 1. SyntaxError / IndentationError / TabError（带 `^` 指针）

### 真实格式

Python 的 `SyntaxError` 有独特的 traceback 格式，与其他异常不同。它显示 `File "x.py", line N`（没有 `, in func_name`）：

```
Traceback (most recent call last):
  File "app.py", line 3
    x = 1 +
           ^
SyntaxError: invalid syntax
```

带前序调用栈：

```
Traceback (most recent call last):
  File "main.py", line 10, in run
    exec(code)
  File "<string>", line 3
    x = 1 +
           ^
SyntaxError: invalid syntax
```

`IndentationError` 和 `TabError` 格式相同：

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

### 为什么失败

`_RE_CALL_SITE` 正则要求 `, in func_name`：

```python
_RE_CALL_SITE = re.compile(
    r'^\s*File "(?P<file>[^"]+)",\s*line\s+(?P<line>\d+),\s*in\s+(?P<func>\S+)',
    re.MULTILINE,
)
```

SyntaxError 的 `File "app.py", line 3`（没有 `, in func`）永远匹配不到。当没有找到任何 call site 时，`_parse_single_block()` 返回 `None`。

### 当前行为（已验证）

| 场景 | 结果 |
|------|------|
| 独立 SyntaxError | 解析出 0 条 trace（静默失败） |
| 有前序调用栈的 SyntaxError | 解析了前序调用栈但**指向错误的 frame** — 最后一个 `in func` 的 frame（如 `main.py:10`），而非 SyntaxError 行（`<string>:3`） |
| `IndentationError` | 解析出 0 条 trace（同样的失败） |
| `TabError` | 解析出 0 条 trace（同样的失败） |

### 需要改动

1. **新增正则** 匹配 SyntaxError 的 call-site 格式：
   ```python
   _RE_CALL_SITE_NO_FUNC = re.compile(
       r'^\s*File "(?P<file>[^"]+)",\s*line\s+(?P<line>\d+)\s*$',
       re.MULTILINE,
   )
   ```

2. **更新 `_parse_single_block()`**：当 `_RE_CALL_SITE` 找不到匹配时，尝试 `_RE_CALL_SITE_NO_FUNC`。

3. **可选：提取列号** — 从 `^` 指针位置计算列号（`^` 在行中的位置 = 列号）。

4. **处理指针和上下文行** — `    x = 1 +` 和 `           ^` 这类行不应被视为 call site 或变量来源。

### 修复后期望行为

```
Traceback (most recent call last):
  File "app.py", line 3
    x = 1 +
           ^
SyntaxError: invalid syntax
```

→ `ParsedTrace(file="app.py", line=3, error="SyntaxError: invalid syntax", chain=["app.py:<module>:3"])`

---

## 2. ExceptionGroup / BaseExceptionGroup（Python 3.11+）

### 真实格式

Python 3.11 引入了 `ExceptionGroup` 和 `BaseExceptionGroup`，用于处理多个并发异常（如 `asyncio.TaskGroup`）。traceback 格式完全不同：

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

与标准 traceback 的关键区别：
- **标题**：`+ Exception Group Traceback (most recent call last):`（不是 `Traceback ...`）
- **前缀**：行首有 `|`（管道符）
- **子异常**：由 `+-+--- N ---` 分隔符分隔
- **多个 trace**：一个 ExceptionGroup 可包含 N 个子异常，每个有自己的 traceback

### 为什么失败

1. `_RE_TRACEBACK_HEADER` 要求 `^Traceback \(most recent call last\):` 在行首。`+ Exception Group Traceback` 标题不匹配。

2. 即使标题匹配了，call-site 行的 `|` 前缀（`|   File "app.py", line 10, in main`）也阻止 `_RE_CALL_SITE` 匹配（它期望 `^\s*File`）。

3. 嵌套的子异常有自己的 `Traceback` 标题和 `|` 前缀，同样不匹配。

### 当前行为（已验证）

- `can_parse()` 返回 `False` — 完全未检测到
- 多子异常的 ExceptionGroup：解析出 0 条 trace
- 单子异常 fixture：只解析了外层 `ExceptionGroup`（1 trace），子异常**被静默丢失**

### 需要改动

1. **扩展 `_RE_TRACEBACK_HEADER`** 同时匹配 `+ Exception Group Traceback`：
   ```python
   _RE_TRACEBACK_HEADER = re.compile(
       r"^(?:\+ )?Traceback \(most recent call last\):", re.MULTILINE
   )
   ```

2. **去除 `|` 前缀** — 预处理行，移除行首的 `|` 和空白。

3. **解析子异常分隔符**（`+-+--- N ---`）— 拆分为独立的子 trace。

4. **返回多个 `ParsedTrace`** — ExceptionGroup 本身一个，每个子异常各一个。

5. **可选：给 `ParsedTrace` 新增字段** 表示父 group 关系。

### 修复后期望行为

输入：
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

→ 3 个 `ParsedTrace`：
- `ParsedTrace(file="app.py", line=10, error="ExceptionGroup: unhandled errors")`
- `ParsedTrace(file="app.py", line=5, error="ValueError: bad")`
- `ParsedTrace(file="app.py", line=8, error="TypeError: wrong")`

---

## 3. Warning 格式

### 真实格式

Python 的 warning 使用与 traceback 不同的输出格式：

```
app.py:10: DeprecationWarning: old_function() is deprecated, use new_function()
  result = old_function()
```

```
/usr/lib/python3.12/json/decoder.py:355: JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

多行 warning：

```
app.py:10: ResourceWarning: unclosed <socket.socket fd=3, family=AddressFamily.AF_INET>
  result = old_function()
ResourceWarning: Enable tracemalloc to get the object allocation traceback
```

### 为什么失败

- 没有 `Traceback (most recent call last):` 头 → `can_parse()` 返回 `False`
- 格式是 `file:line: WarningType: message`（冒号分隔，不是 `File "x.py", line N`）

### 当前行为

- 所有 parser 都无法检测

### 需要改动

1. **创建 `WarningParser(BaseParser)`**：
   - 正则：`^(?P<file>[^:]+):(?P<line>\d+):\s*(?P<warning_type>\w+Warning):\s*(?P<msg>.+)$`
   - 同时处理使用此格式的 `Error` 类型（如 `JSONDecodeError`）

2. **加入 CLI 自动检测** — 在 `_detect_parser()` 中添加。

3. **映射到 `ParsedTrace`**：`file`、`line`、`error` = `"{warning_type}: {msg}"`。

### 修复后期望行为

```
app.py:10: DeprecationWarning: old_function() is deprecated
```

→ `ParsedTrace(file="app.py", line=10, error="DeprecationWarning: old_function() is deprecated")`

---

## 4. RecursionError 深度保留

### 真实格式

当 Python 达到递归限制时，会缩写 traceback：

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

### 当前行为

- 能成功解析，但 `chain` 只有 3 个条目（显示的 3 个 call site）
- `[Previous line repeated 997 more times]` 行被静默忽略
- 真实递归深度（1000）丢失

### 需要改动

1. **检测重复行**：
   ```python
   _RE_RECURSION_REPEAT = re.compile(
       r"^\s*\[Previous line repeated (\d+) more times\]",
       re.MULTILINE,
   )
   ```

2. **存储重复次数** — 两种方案：
   - 给 `ParsedTrace` 新增 `recursion_depth: int | None` 字段
   - 或在 `chain` 中追加合成条目（不推荐 — 会膨胀 chain）

3. **更新 `_parse_single_block()`** — 收集 call site 后扫描此行。

### 修复后期望行为

→ `ParsedTrace(file="app.py", line=2, error="RecursionError: ...", chain=[...], recursion_depth=1000)`

---

## 5. Exception Notes（Python 3.11+ `add_note()`）

### 真实格式

Python 3.11 新增了 `Exception.add_note()` 方法，可为异常附加元数据：

```
Traceback (most recent call last):
  File "app.py", line 10, in process
    result = api.fetch(user_id)
ValueError: bad value
Exception note: This error occurred during the migration phase
```

多个 note：

```
Traceback (most recent call last):
  File "app.py", line 10, in process
    result = api.fetch(user_id)
ValueError: bad value
Exception note: User ID was 12345
Exception note: API endpoint was /api/v2/users
```

### 当前行为

- 异常行（`ValueError: bad value`）能正确解析
- 其后的 note 行被静默忽略
- note 信息从 `ParsedTrace` 中丢失

### 需要改动

1. **检测 note 行** — 出现在异常行之后，非缩进（或轻缩进），以文本开头（不是 `File` 或 `Traceback`）。

2. **给 `ParsedTrace` 新增 `notes: list[str]` 字段**。

3. **解析 notes** — 在 `_parse_single_block()` 中匹配异常行后，继续扫描非缩进文本行直到下一个 traceback 或输入结束。

### 修复后期望行为

→ `ParsedTrace(file="app.py", line=10, error="ValueError: bad value", notes=["User ID was 12345", "API endpoint was /api/v2/users"])`

---

## 6. Logging exc_info 前缀格式

### 真实格式

Python 的 `logging` 模块配合 `exc_info=True` 或 `logging.exception()` 输出的 traceback 带有时间戳和日志级别前缀：

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

不同的 logging formatter 产生不同的前缀模式：
- `logging.Formatter('%(asctime)s %(levelname)s %(name)s')` → `2024-01-15 10:30:45 ERROR [app.main]`
- `logging.Formatter('%(asctime)s %(levelname)s %(module)s')` → `2024-01-15 10:30:45 ERROR main`
- JSON logging → `{"timestamp":"2024-01-15T10:30:45","level":"ERROR","message":"Traceback ..."}`
- 部分框架将 `Traceback` 放在日志头之后的独立行

### 为什么失败

`_RE_TRACEBACK_HEADER` 正则使用 `^` 锚定行首：

```python
_RE_TRACEBACK_HEADER = re.compile(
    r"^Traceback \(most recent call last\):", re.MULTILINE
)
```

当 `Traceback` 前面有 `2024-01-15 10:30:45 ERROR ...` 时，`^` 锚点阻止匹配。整个 traceback 对解析器不可见。

### 当前行为（已验证）

| 场景 | 结果 |
|------|------|
| `Traceback` 与日志前缀在同一行 | 解析出 0 条 trace — `can_parse()` 返回 `False` |
| `Traceback` 在日志头之后的独立行 | 正常工作 — `^` 在行首匹配 |

### 需要改动

1. **放宽 `_RE_TRACEBACK_HEADER`** — 去除 `^` 锚点或增加替代方案：
   ```python
   _RE_TRACEBACK_HEADER = re.compile(
       r"^(?:.*\s)?Traceback \(most recent call last\):", re.MULTILINE
   )
   ```
   或预处理：解析前去除日志前缀。

2. **注意误报** — 自由文本中的 `Traceback` 不应触发解析。可要求下一行是缩进且以 `File` 开头。

### 修复后期望行为

```
2024-01-15 10:30:45 ERROR [app.main] Traceback (most recent call last):
  File "/app/main.py", line 10, in main
    process()
RuntimeError: API connection failed
```

→ `ParsedTrace(file="/app/main.py", line=10, error="RuntimeError: API connection failed")`

---

## 7. Re-raise 标注（无参数 `raise`）

### 真实格式

Python 允许用裸 `raise` 重新抛出当前异常：

```python
try:
    result = api.fetch(data)
except ConnectionError:
    logger.error("API unavailable")
    raise  # re-raises ConnectionError
```

产生的 traceback：

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

### 当前行为

- 解析器将裸 `raise` 与任何其他 traceback 同等处理
- 两个 trace 都正确解析了调用链
- **没有标注**第二个 trace 是 re-raise

### 需要改动

1. **检测裸 `raise`** — 当异常源码行只是 `raise`（无参数）时，标记为 re-raise。

2. **可选新增 `is_reraise: bool` 字段**到 `ParsedTrace`。

3. **复现上下文** — 对于 re-raise，复现脚本应包含 `try/except/raise` 包装，而非裸 `raise`。

### 修复后期望行为

→ `ParsedTrace(file="app.py", line=7, error="ConnectionError: Connection refused", is_reraise=True)`

---

## 8. Doctest 格式

### 真实格式

Python 的 `doctest` 模块产生独特的错误格式：

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

### 为什么失败

- `Traceback` 头在嵌套上下文中（`Exception raised:` 之后）
- Call-site 行有额外缩进（6 个空格而非 2 个）
- 周围的 `****` 行和 `Failed example:` / `Exception raised:` 标签不属于 traceback

### 当前行为

- 解析出 0 条 trace — 嵌套的 `Traceback` 被找到但额外缩进可能导致问题

### 需要改动

1. **预处理**：去除 doctest 框架（`****` 行、`Failed example:`、`Exception raised:` 标签）。

2. **或**：识别 doctest 格式并提取内嵌的 traceback。

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **低** | Doctest 很少是生产错误的来源 |
| 实现难度 | **低** | 去除框架，解析内嵌 traceback |
| 复现价值 | **低** | Doctest 错误通常很直接 |

---

## 9. pytest 短回溯格式

### 真实格式

pytest 在完整 traceback 之前显示短的断言内省格式：

```
FAILED test_example.py::test_divide - assert 2.0 == 3.0

========================= short test summary info =========================
FAILED test_example.py::test_divide - assert 2.0 == 3.0
============================== 1 failed in 0.12s ==============================
```

完整 traceback（pytest 同时显示）使用标准 Python 格式，**已被正确解析**。只有短摘要使用不同格式。

### 为什么失败

- 没有 `Traceback (most recent call last):` 头
- 格式是 `FAILED path::test_name - assertion_message`

### 当前行为

- 短摘要：解析出 0 条 trace（符合预期 — 不是 traceback）
- 完整 traceback：正确解析

### 需要改动

- **log2repro 主用例无需改动** — 完整 traceback 才是复现所需的关键信息
- 短格式仅用于信息展示（测试名 + 断言）

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **低** | 仅与 pytest 输出相关 |
| 实现难度 | **不适用** | 完整 traceback 已可用 |
| 复现价值 | **无** | 短格式无源码上下文 |

---

## 10. LLM API 错误 JSON 响应

### 真实格式

LLM 提供商通过 HTTP 响应返回结构化 JSON 错误。各提供商格式不同：

**OpenAI 风格：**
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

**Anthropic 风格：**
```json
{
  "type": "error",
  "error": {
    "type": "authentication_error",
    "message": "Invalid API Key"
  }
}
```

**LiteLLM 统一风格：**
```json
{
  "error": {
    "message": "Rate limit exceeded",
    "type": "RateLimitError",
    "code": "429"
  }
}
```

### 为什么失败

- 没有 `Traceback` 头 → 所有 parser 的 `can_parse()` 返回 `False`
- 格式是 JSON，不是 Python traceback 文本
- 各提供商的错误字段不同（`error.type` vs `error.error.type`）

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **高** | 每个 LLM 集成都可能遇到 API 错误 |
| 格式稳定性 | **高** | JSON schema 在各提供商中定义明确 |
| 实现难度 | **低** | 标准 JSON 解析，无需复杂正则 |
| 复现价值 | **中** | 可生成带 mock API 响应的重试/降级代码 |

### 实现说明

1. **创建 `APIErrorParser(BaseParser)`**：
   - `can_parse()`：尝试 `json.loads()`，检查是否存在 `error` 键
   - 兼容 OpenAI、Anthropic、LiteLLM 的字段差异

2. **提取为 `ParsedTrace`**：
   - `error` = `"{type}: {message}"`
   - `file` / `line` = 空（API 错误无源码位置）
   - 元数据：`provider`、`error_code`、`error_type`

3. **复现策略**：生成一个触发相同错误处理路径的 mock API 响应代码。

---

## 11. MCP JSON-RPC 错误

### 真实格式

MCP（Model Context Protocol）服务器通过 JSON-RPC 2.0 通信。错误出现在 stderr：

```json
{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"Invalid Request"}}
```

```json
{"jsonrpc":"2.0","id":2,"error":{"code":-32601,"message":"Method not found","data":{"method":"tools/unknown"}}}
```

```json
{"jsonrpc":"2.0","id":3,"error":{"code":-32000,"message":"Server error","data":{"detail":"database connection failed"}}}
```

**标准 JSON-RPC 错误码：**
| 错误码 | 含义 |
|--------|------|
| -32700 | 解析错误 |
| -32600 | 无效请求 |
| -32601 | 方法未找到 |
| -32602 | 无效参数 |
| -32603 | 内部错误 |
| -32000 到 -32099 | 服务器错误（保留） |

### 为什么失败

- JSON 格式出现在 stderr 中，无 traceback 结构
- 与其他 stderr 输出（日志、警告）混合
- 错误码需要映射为人类可读类型

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **中** | 随 MCP 普及增长 |
| 格式稳定性 | **高** | JSON-RPC 2.0 是稳定规范 |
| 实现难度 | **低** | JSON 解析 + 错误码映射 |
| 复现价值 | **中** | 可生成带 mock 服务器响应的 MCP 客户端代码 |

### 实现说明

1. **创建 `MCPRpcParser(BaseParser)`**：
   - `can_parse()`：查找包含 `{"jsonrpc":"2.0"` 和 `"error"` 键的模式
   - 从混合 stderr 中提取：过滤包含有效 JSON-RPC 的行

2. **映射错误码到类型**：
   ```python
   _JSONRPC_ERROR_MAP = {
       -32700: "ParseError",
       -32600: "InvalidRequest",
       -32601: "MethodNotFound",
       -32602: "InvalidParams",
       -32603: "InternalError",
   }
   ```

3. **提取为 `ParsedTrace`**：
   - `error` = `"{映射类型}: {message}"`
   - 元数据：`jsonrpc_code`、`method`（如果在 `data` 中）

---

## 12. LangChain Agent 详细输出

### 真实格式

LangChain agent 在 verbose 模式下输出 `Thought/Action/Observation` 链：

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

截断错误格式：
```
[AgentError] Tool execution failed: search_database
Error: TimeoutError: connection timed out after 30s
```

### 为什么失败

- 没有 Python traceback — 自由文本格式带结构化段落
- 错误嵌入在 `Observation` 行中，不是独立的
- 单个链中可能有多种错误类型（数据库、HTTP、超时）

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **中** | LangChain/Agent 调试中常见 |
| 格式稳定性 | **低-中** | LangChain 不同版本会更改 verbose 格式 |
| 实现难度 | **中** | 基于段落的解析，非简单正则 |
| 复现价值 | **高** | 可生成失败的工具调用及 mock 响应 |

### 实现说明

1. **创建 `AgentLogParser(BaseParser)`**：
   - `can_parse()`：查找 `Thought:` / `Action:` / `Observation:` 模式
   - 将链解析为段落

2. **从 `Observation` 行提取错误**：
   - 以 `Error:` 开头或包含 HTTP 错误码的行
   - `[AgentError]` 前缀的行

3. **提取为 `ParsedTrace`**：
   - `error` = 失败 Observation 中的错误消息
   - `file` / `line` = 空
   - 元数据：`tool_name`、`tool_input`、`chain_steps`

---

## 13. Token / 上下文窗口限制错误

### 真实格式

**上下文长度超限：**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "This model's maximum context length is 128000 tokens. However, your messages resulted in 150000 tokens. Please reduce the length of the messages.", 'type': 'invalid_request_error', 'param': 'messages', 'code': 'context_length_exceeded'}}
```

**速率限制：**
```
openai.RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for gpt-4 in organization org-xxx on tokens per min (TPM): Limit 10000, Used 9500, Requested 1000. Please try again in 3s.', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
```

**Anthropic 风格：**
```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'prompt is too long: 200000 tokens > 100000 maximum'}}
```

### 为什么失败

- 看起来像 Python 异常行，但消息是嵌入的 JSON 字符串
- 实际错误细节（token 数、模型名、重试时间）在 JSON 载荷内部
- 当前 parser 将整个字符串提取为错误消息，丢失结构化数据

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **高** | LLM 应用中非常常见 |
| 格式稳定性 | **中** | 消息格式各异但总包含 token 数 |
| 实现难度 | **低** | 从已知模式中用正则或 JSON 提取 |
| 复现价值 | **高** | 可生成截断输入以适应上下文的代码 |

### 实现说明

1. **创建 `LLMErrorParser(BaseParser)`**：
   - `can_parse()`：匹配错误文本中的 `token`、`context_length`、`rate_limit` 等模式
   - 从嵌入的 JSON 中提取结构化数据

2. **解析 token 数量和限制**：
   ```python
   _RE_TOKEN_ERROR = re.compile(
       r"(?:maximum context length|context_length_exceeded).*?(\d+)\s*tokens"
   )
   _RE_RATE_LIMIT = re.compile(
       r"Rate limit.*?try again in (\d+)(s|ms)"
   )
   ```

3. **提取为 `ParsedTrace`**：
   - `error` = `"{错误类型}: {人类可读摘要}"`
   - 元数据：`model`、`token_used`、`token_limit`、`retry_after`

---

## 14. Agent 工具执行错误（截断格式）

### 真实格式

Agent 框架通常截断工具错误以简洁输出：

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

### 为什么失败

- `[AgentError]` / `[ToolError]` 前缀不是标准 Python traceback 格式
- 实际错误在后续行中，缩进通常不同
- 超时错误没有异常类型 — 只有消息

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **中** | Agent 调试中常见 |
| 格式稳定性 | **低** | 框架特定的前缀 |
| 实现难度 | **低** | 简单前缀 + 内容提取 |
| 复现价值 | **高** | 可生成失败的工具调用 |

### 实现说明

1. **扩展 `AgentLogParser`** 或创建独立处理：
   - 匹配 `[AgentError]`、`[ToolError]` 前缀
   - 从 "Tool execution failed: {name}" 提取工具名
   - 捕获后续错误行

2. **提取为 `ParsedTrace`**：
   - `error` = 嵌入的错误消息
   - 元数据：`tool_name`、`is_timeout`

---

## 15. SSE 流式错误块

### 真实格式

LLM 流式 API 通过 SSE（Server-Sent Events）块发送错误：

```
data: {"error":{"message":"The server had an error processing your request","type":"server_error","code":null}}
```

```
event: error
data: {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}
```

与正常流混合：
```
data: {"choices":[{"delta":{"content":"Hello"}}]}

data: {"choices":[{"delta":{"content":" world"}}]}

data: [DONE]

data: {"error":{"message":"Request timed out","type":"timeout","code":"timeout"}}
```

### 为什么失败

- SSE 格式（`data: ` 前缀）不被任何 parser 识别
- 错误与正常流数据混合
- JSON 嵌入在 `data: ` 前缀之后

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **中** | 所有流式 LLM 调用 |
| 格式稳定性 | **高** | SSE 是定义明确的规范 |
| 实现难度 | **低** | 去除 `data: ` 前缀，解析 JSON |
| 复现价值 | **中** | 可生成等效的非流式代码触发相同错误 |

### 实现说明

1. **扩展 `APIErrorParser`** 处理 SSE 格式：
   - 去除 `data: ` 和 `event: ` 前缀
   - 解析剩余 JSON 中的错误对象
   - 过滤掉 `data: [DONE]`

2. **提取为 `ParsedTrace`**：
   - 与 §10 LLM API 错误 JSON 相同
   - 元数据：`is_streaming=True`

---

## 16. 图片 / Vision API 错误

### 真实格式

Vision API 错误有独特的模式：

```
openai.BadRequestError: Error code: 400 - {'error': {'message': 'Invalid image URL: Unable to download image from https://example.com/invalid.jpg', 'type': 'invalid_request_error', 'param': 'messages[0].content[1].image_url.url', 'code': 'invalid_image_url'}}
```

```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Image exceeds maximum size of 20MB. Received: 25.3MB'}}
```

```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid MIME type 'application/pdf' for image content. Supported types: image/png, image/jpeg, image/gif, image/webp", 'type': 'invalid_request_error', 'code': 'invalid_image_format'}}
```

### 为什么失败

- 与 §10 相同 — JSON 错误格式，不是 Python traceback
- 有标准 LLM 错误模式未覆盖的独特错误类型
- 错误消息引用特定的媒体约束

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **中** | 随多模态采用率增长 |
| 格式稳定性 | **高** | 与 §10 相同的 JSON 结构 |
| 实现难度 | **低** | 由 §10 的 `APIErrorParser` 处理 |
| 复现价值 | **中** | 可生成有效/无效图片的代码 |

### 实现说明

- **无需独立 parser** — 由 `APIErrorParser`（§10）处理
- **新增多模态错误码**到错误类型映射：
  - `invalid_image_url`、`invalid_image_format`、`image_too_large`
- **元数据**：`media_type`、`file_size`、`param`（指向有问题的 content part）

---

## 17. Google Gemini API 错误

### 真实格式

Google 的 Gemini API 使用 `google.api_core.exceptions` 类和独特的 JSON 错误格式：

**HTTP 响应体：**
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

**Python SDK 异常：**
```
google.api_core.exceptions.InvalidArgument: 400 Invalid value at 'contents[0].parts[0].text' (TYPE_STRING), ""
```

**`google-genai` SDK (v1.x)：**
```
google.genai.errors.ClientError: 400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': '...', 'status': 'INVALID_ARGUMENT'}}
```

**常见错误类型：**
| 异常类 | HTTP 状态码 | gRPC 状态 |
|--------|------------|-----------|
| `BadRequest` / `InvalidArgument` | 400 | INVALID_ARGUMENT |
| `Forbidden` / `PermissionDenied` | 403 | PERMISSION_DENIED |
| `NotFound` | 404 | NOT_FOUND |
| `TooManyRequests` / `ResourceExhausted` | 429 | RESOURCE_EXHAUSTED |
| `InternalServerError` | 500 | INTERNAL |
| `ServiceUnavailable` | 503 | UNAVAILABLE |

### 为什么失败

- 错误格式是 Google 特有的（`error.code` + `error.status` + `error.details`），不同于 OpenAI/Anthropic 风格
- Python 异常使用 `google.api_core.exceptions` 层级，不是标准 HTTP 错误类
- `google-genai` SDK 将错误包装为 `ClientError`/`ServerError`，消息格式不同

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **高** | 第三大 LLM 提供商 |
| 格式稳定性 | **高** | Google API 错误格式成熟稳定 |
| 实现难度 | **低** | JSON 解析 + 异常类映射 |
| 复现价值 | **中** | 可生成带 mock 响应的重试/降级代码 |

### 实现说明

1. **扩展 `APIErrorParser`** 或创建 `GeminiErrorParser`：
   - 解析 Google JSON 错误格式（`error.code`、`error.status`、`error.message`）
   - 映射 `google.api_core.exceptions` 类名到错误类型
   - 处理 `google-genai` SDK 的 `ClientError`/`ServerError` 包装

2. **提取为 `ParsedTrace`**：
   - `error` = `"{status}: {message}"`
   - 元数据：`grpc_status`、`http_code`、`provider="google"`

---

## 18. A2A 协议错误（Agent-to-Agent）

### 真实格式

Google 的 A2A（Agent-to-Agent）协议使用 JSON-RPC 2.0，有 5 个协议专属错误码：

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

**A2A 专属错误码：**
| 错误码 | 名称 | 说明 |
|--------|------|------|
| -32001 | Task not found | 引用的任务不存在 |
| -32002 | Task cannot be canceled | 任务不在可取消状态 |
| -32003 | Push notification not supported | Agent 不支持推送通知 |
| -32004 | Unsupported operation | 此 Agent 不支持的操作 |
| -32005 | Content type not supported | Agent 无法处理请求的内容类型 |

加上标准 JSON-RPC 错误码：-32700（解析错误）、-32600（无效请求）、-32601（方法未找到）、-32602（无效参数）、-32603（内部错误）。

### 为什么失败

- 与 MCP（§11）相同 — JSON-RPC 格式，无 Python traceback
- A2A 专属错误码（-32001 到 -32005）不在标准 JSON-RPC 错误码表中
- 错误出现在 HTTP 响应体或 WebSocket 消息中

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **中** | 新兴协议，与 MCP 并列增长 |
| 格式稳定性 | **高** | JSON-RPC 2.0 稳定；A2A 错误码在规范中定义 |
| 实现难度 | **低** | 扩展 MCP 解析器，增加 A2A 专属错误码映射 |
| 复现价值 | **中** | 可生成带 mock Agent 响应的 A2A 客户端代码 |

### 实现说明

1. **扩展 `MCPRpcParser`** 或创建 `A2AErrorParser`：
   - 解析 JSON-RPC 2.0 错误格式（与 MCP 相同）
   - 新增 A2A 专属错误码映射（-32001 到 -32005）
   - 从请求/响应元数据检测 A2A 上下文

2. **提取为 `ParsedTrace`**：
   - `error` = `"{映射类型}: {message}"`
   - 元数据：`protocol="a2a"`、`jsonrpc_code`、`task_id`

---

## 19. 内容审核/安全过滤错误

### 真实格式

**OpenAI：**
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

**Anthropic：**
```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Output blocked by content filtering policy'}}
```

**Google Gemini：**
```
google.api_core.exceptions.InvalidArgument: 400 Request contains potentially harmful content (SAFETY)
```

**LiteLLM：**
```python
litellm.ContentPolicyViolationError: OpenAIException: Your request was rejected as a result of our safety system.
```

### 为什么失败

- 这些是 API 错误（由 §10 `APIErrorParser` 处理），但 `code`/`type` 各不相同：
  - OpenAI：`code: "content_policy_violation"`
  - Anthropic：嵌入在消息文本中
  - Google：消息中包含 `SAFETY`
  - LiteLLM：`ContentPolicyViolationError` 异常类
- 安全类别信息通常嵌入在消息中，不是结构化的

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **高** | 用户生成内容场景常见 |
| 格式稳定性 | **中** | 提供商特定的 code，消息格式各异 |
| 实现难度 | **低** | 扩展 `APIErrorParser` 增加内容策略检测 |
| 复现价值 | **中** | 可生成测试内容策略边界的代码 |

### 实现说明

1. **扩展 `APIErrorParser`** 检测内容策略错误：
   - 检查 `content_policy_violation` code（OpenAI）
   - 检查消息中的 `safety` / `content filtering`（Anthropic、Google）
   - 检查 `ContentPolicyViolationError` 类（LiteLLM）

2. **提取为 `ParsedTrace`**：
   - `error` = `"ContentPolicyViolation: {message}"`
   - 元数据：`provider`、`violation_category`（如可提取）

---

## 20. Tool Calling / Function Calling 错误

### 真实格式

**JSON Schema 验证失败（OpenAI strict 模式）：**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid schema for function 'get_weather': In context=('properties', 'date'), 'format' is not supported in strict mode. Use 'pattern' instead.", 'type': 'invalid_request_error', 'param': 'tools[0].function.parameters', 'code': 'invalid_schema'}}
```

**工具参数类型不匹配：**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid parameter: 'temperature' must be a number, got string", 'type': 'invalid_request_error', 'param': 'temperature', 'code': 'invalid_type'}}
```

**OpenAI Assistants API — run 需要 action：**
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

**工具输出格式错误：**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid tool call output: expected JSON, got 'success'", 'type': 'invalid_request_error', 'code': 'invalid_tool_output'}}
```

### 为什么失败

- Schema 验证错误是 API 错误（由 §10 处理），但错误消息引用了特定的 JSON Schema 字段
- `requires_action` 状态不是错误 — 是 Assistants API 中的控制流信号
- 工具输出格式错误有独特的 `code: "invalid_tool_output"`

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **高** | 每个 tool-calling 集成都会遇到 |
| 格式稳定性 | **中** | OpenAI strict 模式的 schema 限制会变化 |
| 实现难度 | **低** | 扩展 `APIErrorParser` 增加 tool 专属 code |
| 复现价值 | **高** | 可生成修正后的 schema/tool 调用代码 |

### 实现说明

1. **扩展 `APIErrorParser`** 检测 tool calling 错误：
   - 检查 `invalid_schema`、`invalid_type`、`invalid_tool_output` code
   - 解析 `param` 字段识别失败的 tool/参数
   - 检测 Assistants API 响应中的 `requires_action` 状态

2. **提取为 `ParsedTrace`**：
   - `error` = `"{code}: {message}"`
   - 元数据：`tool_name`、`param`、`schema_field`

---

## 21. OpenAI Responses API 错误

### 真实格式

Responses API（2025 年 3 月发布）使用 SSE 事件进行流式传输。错误通过 `response.failed` 事件到达：

```
event: response.failed
data: {"type":"response.failed","response":{"id":"resp_abc","object":"response","status":"failed","error":{"type":"server_error","code":"internal_error","message":"An internal error occurred"}}}
```

**非流式错误：**
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

**状态值：** `completed`、`failed`、`cancelled`、`expired`

### 为什么失败

- 错误嵌套在 `response.failed` SSE 事件中，不是简单的 JSON 错误
- 错误对象结构与 Chat Completions 相同，但信封不同
- 流式错误需要先解析 SSE 事件再提取错误

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **中** | 新 API，采用率增长中 |
| 格式稳定性 | **高** | OpenAI 新标准 API |
| 实现难度 | **低** | 扩展 SSE 解析器（§15）处理 Responses API 信封 |
| 复现价值 | **中** | 可生成等效的非流式代码 |

### 实现说明

1. **扩展 `APIErrorParser`** 处理 Responses API 信封：
   - 解析 SSE 事件，检测 `response.failed` 类型
   - 提取 `response.error` 对象（与 Chat Completions 错误结构相同）
   - 处理非流式的 `status: "failed"` 响应

2. **提取为 `ParsedTrace`**：
   - 与 §10 LLM API 错误 JSON 相同
   - 元数据：`api="responses"`、`response_id`、`status`

---

## 22. Agent 框架错误（CrewAI / AutoGen / Google ADK / Semantic Kernel）

### 真实格式

**CrewAI：**
```
crewai.exceptions.AgentExecutionError: Agent 'Researcher' failed to complete task: LLM rate limit exceeded after 3 retries
```
```
crewai.exceptions.CrewError: Crew execution failed: All agents failed to complete their tasks
```

**AutoGen（Microsoft）：**
```
autogen.exceptions.TerminationException: Group chat terminated: max_rounds (10) reached without consensus
```
```
autogen.exceptions.GroupChatError: Agent 'critic' raised an unexpected error: API connection failed
```

**Google ADK：**
```
google.adk.errors.ToolError: Tool 'search_web' execution failed: HTTP 429 Too Many Requests
```
```
google.adk.errors.AgentError: Agent 'planner' failed: Unable to parse LLM response as valid JSON
```

**Semantic Kernel（Microsoft）：**
```
semantic_kernel.exceptions.KernelInvokeError: Function 'SearchPlugin.Search' invocation failed: OpenAI rate limit exceeded
```

### 为什么失败

- 每个框架将 LLM/工具错误包装在自己的异常层级中
- 原始 LLM 错误嵌套在异常消息或 `__cause__` 中
- 不同框架使用不同的命名：`AgentExecutionError`、`TerminationException`、`ToolError`、`KernelInvokeError`

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **中** | Agent 调试中常见 |
| 格式稳定性 | **低** | 框架 API 变化频繁 |
| 实现难度 | **中** | 需要检测多个框架模式 |
| 复现价值 | **高** | 可生成失败的 agent/tool 调用 |

### 实现说明

1. **创建 `AgentFrameworkParser(BaseParser)`**：
   - `can_parse()`：检测框架特定的异常类名
   - 解析框架错误包装，提取底层错误
   - 支持 CrewAI、AutoGen、Google ADK、Semantic Kernel

2. **提取为 `ParsedTrace`**：
   - `error` = 底层错误（如 "LLM rate limit exceeded"）
   - 元数据：`framework`、`agent_name`、`original_error_type`

---

## 23. LiteLLM 统一异常体系

### 真实格式

LiteLLM 定义了 8 个异常类，映射所有提供商的错误：

```python
import litellm

try:
    response = litellm.completion(model="gpt-4", messages=[...])
except litellm.AuthenticationError as e:
    # 401 — 所有提供商
    print(f"Auth failed: {e.message}")
except litellm.RateLimitError as e:
    # 429 — 所有提供商
    print(f"Rate limited: {e.message}, retry after {e.retry_after}s")
except litellm.ContextWindowExceededError as e:
    # 400 — token 限制
    print(f"Context too long: {e.message}")
except litellm.BudgetExceededError as e:
    # 429 — 预算限制
    print(f"Budget exceeded: {e.message}")
except litellm.ContentPolicyViolationError as e:
    # 400 — 安全过滤
    print(f"Content blocked: {e.message}")
except litellm.InvalidRequestError as e:
    # 400 — 错误请求
    print(f"Invalid request: {e.message}")
except litellm.ServiceUnavailableError as e:
    # 503 — 提供商宕机
    print(f"Service unavailable: {e.message}")
except litellm.Timeout as e:
    # 408 — 超时
    print(f"Timeout: {e.message}")
```

**LiteLLM Proxy 统一 JSON 错误：**
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

### 为什么失败

- LiteLLM 的异常类不是标准 HTTP 错误 — 是统一映射层
- Proxy 的 JSON 格式类似 OpenAI 但使用 LiteLLM 的 `type` 值（如 `RateLimitError` vs `rate_limit_error`）
- §10 覆盖了基本 JSON 格式但未覆盖完整的异常层级

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **高** | LiteLLM 是最流行的 LLM 网关/代理 |
| 格式稳定性 | **高** | 稳定的异常层级 |
| 实现难度 | **低** | 映射 LiteLLM 异常名到错误类型 |
| 复现价值 | **中** | 可生成重试/降级代码 |

### 实现说明

1. **扩展 `APIErrorParser`** 识别 LiteLLM 异常名：
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

2. **提取为 `ParsedTrace`**：
   - `error` = `"{映射类型}: {message}"`
   - 元数据：`provider`（来自 LiteLLM）、`original_error_type`

---

## 24. Anthropic Extended Thinking 错误

### 真实格式

```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'thinking.budget_tokens: must be less than max_tokens'}}
```

```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'thinking.type: must be enabled when streaming thinking content'}}
```

```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Extended thinking is not supported for model claude-3-5-sonnet-20241022'}}
```

### 为什么失败

- 这些是标准 Anthropic API 错误（由 §10 处理），但带有 thinking 专属消息
- 错误消息中的 `thinking.*` 参数路径是此功能特有的

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **低** | Extended thinking 是较新功能 |
| 格式稳定性 | **低** | 功能仍在演进 |
| 实现难度 | **无** | 已由 §10 `APIErrorParser` 处理 |
| 复现价值 | **低** | 可生成修正后的 thinking 配置 |

### 实现说明

- **无需独立 parser** — 由 `APIErrorParser`（§10）处理
- **新增 thinking 专属检测**到元数据：当消息包含 `thinking.*` 时标记 `feature="extended_thinking"`

---

## 25. Embedding API 错误

### 真实格式

**OpenAI：**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "This model's maximum context length is 8191 tokens, however you sent 10000 tokens", 'type': 'invalid_request_error', 'param': 'input', 'code': 'context_length_exceeded'}}
```

**维度不匹配：**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid 'dimensions' param: requested 256 but model outputs 1536 dimensions", 'type': 'invalid_request_error', 'param': 'dimensions', 'code': 'invalid_value'}}
```

**批量大小超限：**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Too many inputs. Maximum 2048, got 5000", 'type': 'invalid_request_error', 'param': 'input', 'code': 'too_many_inputs'}}
```

### 为什么失败

- 标准 API 错误（由 §10 处理），但带有 embedding 专属的错误码和参数
- `param` 字段指向 embedding 专属参数（`input`、`dimensions`）

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **中** | RAG/向量搜索应用中常见 |
| 格式稳定性 | **高** | 与 §10 相同 |
| 实现难度 | **无** | 已由 §10 `APIErrorParser` 处理 |
| 复现价值 | **中** | 可生成修正后的 embedding 调用 |

### 实现说明

- **无需独立 parser** — 由 `APIErrorParser`（§10）处理
- **新增 embedding 专属元数据**：`api="embeddings"`、`input_tokens`、`requested_dimensions`

---

## 26. Batch API 错误

### 真实格式

**OpenAI Batch API — batch 失败状态：**
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

**Batch 输出中的单个请求失败：**
```json
{"id": "batch_req_001", "response": {"status_code": 400, "body": {"error": {"message": "...", "type": "invalid_request_error"}}}, "error": null}
{"id": "batch_req_002", "response": null, "error": {"code": "rate_limit_exceeded", "message": "Rate limit exceeded"}}
```

### 为什么失败

- Batch 错误有不同的信封：`status: "failed"` + `errors.data` 数组
- Batch 输出中的单个请求失败有 `response.status_code` 或 `error` 字段
- Batch 级别的错误不是标准 API 错误响应

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **低** | Batch API 使用较少 |
| 格式稳定性 | **高** | OpenAI Batch API 稳定 |
| 实现难度 | **低** | 解析 batch 状态 JSON，提取错误摘要 |
| 复现价值 | **低** | Batch 错误通常是输入数据问题 |

### 实现说明

1. **扩展 `APIErrorParser`** 检测 batch 错误：
   - 解析 `status: "failed"` + `errors.data` 数组
   - 提取错误摘要（数量、第一个错误消息）

2. **提取为 `ParsedTrace`**：
   - `error` = `"BatchError: {第一个错误消息}"`
   - 元数据：`batch_id`、`total`、`failed_count`

---

## 27. Realtime API WebSocket 错误

### 真实格式

OpenAI 的 Realtime API 通过 WebSocket 发送错误消息：

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

**连接级错误：**
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

**会话级错误：**
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

### 为什么失败

- WebSocket 消息不是 HTTP 响应 — 没有状态码
- 错误信封使用 `"type": "error"` 或 `"type": "session.error"`
- 错误对象结构类似 OpenAI HTTP 错误但有额外字段（`event_id`、`param`）

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **低** | Realtime API 较新，采用率有限 |
| 格式稳定性 | **中** | API 仍在演进 |
| 实现难度 | **低** | 解析带 error 类型的 WebSocket JSON 消息 |
| 复现价值 | **低** | Realtime API 错误通常是连接问题 |

### 实现说明

1. **扩展 `APIErrorParser`** 处理 WebSocket 错误消息：
   - 检测 JSON 中的 `"type": "error"` 或 `"type": "session.error"`
   - 提取嵌套的 `error` 对象（与 HTTP 错误结构相同）

2. **提取为 `ParsedTrace`**：
   - `error` = `"{code}: {message}"`
   - 元数据：`transport="websocket"`、`event_id`

---

## 28. 音频 API 错误（Whisper / TTS / Realtime Voice）

### 真实格式

**Whisper 语音转写 — 不支持的编码：**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid file format. Supported formats: ['flac', 'm4a', 'mp3', 'mp4', 'mpeg', 'mpga', 'oga', 'ogg', 'wav', 'webm']", 'type': 'invalid_request_error', 'param': 'file', 'code': 'invalid_file_format'}}
```

**Whisper — 文件过大：**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': 'File size exceeds maximum of 25MB', 'type': 'invalid_request_error', 'param': 'file', 'code': 'file_too_large'}}
```

**TTS — 无效 voice：**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid voice: 'custom_voice'. Available voices: alloy, echo, fable, onyx, nova, shimmer", 'type': 'invalid_request_error', 'param': 'voice', 'code': 'invalid_value'}}
```

**TTS — 输入过长：**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': 'Input text is too long. Maximum 4096 characters, got 5000', 'type': 'invalid_request_error', 'param': 'input', 'code': 'max_characters_exceeded'}}
```

**Realtime Voice — 音频格式错误：**
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

### 为什么失败

- 标准 API 错误（由 §10 `APIErrorParser` 处理），但带有音频专属错误码
- 音频 API 端点有独特参数（`file`、`voice`、`input`、`response_format`）
- Realtime Voice 错误使用 WebSocket 格式（§27）

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **中** | 语音转写/合成应用中常见 |
| 格式稳定性 | **高** | 与 §10 相同 |
| 实现难度 | **无** | 已由 §10 `APIErrorParser` 处理 |
| 复现价值 | **中** | 可生成修正后的音频 API 调用 |

### 实现说明

- **无需独立 parser** — 由 `APIErrorParser`（§10）处理
- **新增音频专属元数据**：`api="audio"`、`endpoint="transcriptions"|"speech"`、`file_format`、`voice`

---

## 29. 文档/PDF 输入错误

### 真实格式

**Anthropic — PDF 过大：**
```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Document size exceeds maximum of 10MB. Received: 15.2MB'}}
```

**Anthropic — 无效文档编码：**
```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Invalid document: could not decode base64 content'}}
```

**Anthropic — 不支持的文档类型：**
```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': "Unsupported document media type: 'application/msword'. Supported: application/pdf"}}
```

**Google Gemini — 文件上传 MIME 错误：**
```
google.api_core.exceptions.InvalidArgument: 400 Unsupported MIME type: 'application/epub+zip'
```

**Google Gemini — 文件上传大小错误：**
```
google.api_core.exceptions.InvalidArgument: 400 File size exceeds maximum of 2GB
```

**OpenAI Assistants — 文件上传错误：**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid file type: 'application/pdf'. Supported types for this endpoint: ['text/plain', 'text/csv', 'application/json']", 'type': 'invalid_request_error', 'param': 'file', 'code': 'invalid_file_type'}}
```

### 为什么失败

- 各提供商文档支持不同：Anthropic（PDF 通过 `document` block）、Gemini（任意文件通过 `files.upload()`）、OpenAI（文本文件通过 Assistants）
- 错误格式是提供商特定的，但遵循其标准 API 错误模式
- 文档专属参数（`media_type`、`file_size`、`base64` 编码）

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **中** | 文档处理场景增长中 |
| 格式稳定性 | **高** | 与各提供商 §10 相同 |
| 实现难度 | **无** | 已由 §10 `APIErrorParser` 处理 |
| 复现价值 | **中** | 可生成修正后的文档上传代码 |

### 实现说明

- **无需独立 parser** — 由 `APIErrorParser`（§10）处理
- **新增文档专属元数据**：`media_type`、`file_size`、`encoding="base64"`、`provider`

---

## 30. Google Gemini 多模态错误

### 真实格式

**视频上传 — 不支持的格式：**
```
google.api_core.exceptions.InvalidArgument: 400 Unsupported MIME type: 'video/avi'. Supported: video/mp4, video/mov, video/webm
```

**视频 — 时长过长：**
```
google.api_core.exceptions.InvalidArgument: 400 Video duration exceeds maximum of 2 hours. Received: 3h 15m
```

**视频 — 处理失败：**
```
google.api_core.exceptions.InternalServerError: 500 Failed to process video: frame extraction failed at 45.2s
```

**音频 — 不支持的格式：**
```
google.api_core.exceptions.InvalidArgument: 400 Unsupported MIME type: 'audio/aac'. Supported: audio/mpeg, audio/wav, audio/ogg, audio/flac
```

**File API — 上传失败：**
```
google.api_core.exceptions.InvalidArgument: 400 Invalid file URI: 'gs://bucket/file.mp4'. Expected format: files/{file_id}
```

**File API — 文件未就绪：**
```
google.api_core.exceptions.FailedPrecondition: 400 File 'files/abc123' is still processing. Status: PROCESSING
```

**多模态 token 溢出：**
```
google.api_core.exceptions.InvalidArgument: 400 Total token count (250000) exceeds model limit (1048576). Note: video tokens are calculated at 1 token per second.
```

### 为什么失败

- Google Gemini 有最广泛的多模态支持（图片、视频、音频、PDF），使用独特的 File API
- 文件处理是异步的 — 文件经历 `PROCESSING` → `ACTIVE` 状态
- Token 计算按媒体类型不同（视频：1 token/秒，图片：基于分辨率）
- 错误格式遵循 Google API 模式（§17），但有多模态专属消息

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **中** | 随 Gemini 多模态采用率增长 |
| 格式稳定性 | **高** | Google API 错误格式 |
| 实现难度 | **无** | 由 §17 `GeminiErrorParser` 处理 |
| 复现价值 | **中** | 可生成修正后的多模态 API 调用 |

### 实现说明

- **无需独立 parser** — 由 `GeminiErrorParser`（§17）处理
- **新增多模态元数据**：`media_type`、`file_id`、`processing_status`、`duration`、`token_count`

---

## 31. 图片生成 API 错误（DALL-E / Imagen）

### 真实格式

**DALL-E — 内容策略违规（生成特有）：**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': 'Your request was rejected by the safety system. The prompt contains content that violates our usage policies.', 'type': 'invalid_request_error', 'param': 'prompt', 'code': 'content_policy_violation'}}
```

**DALL-E — 无效 size：**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid size: '1920x1080'. Supported sizes for dall-e-3: 1024x1024, 1792x1024, 1024x1792", 'type': 'invalid_request_error', 'param': 'size', 'code': 'invalid_value'}}
```

**DALL-E — prompt 过长：**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': 'Prompt is too long. Maximum 4000 characters for dall-e-3, got 5000', 'type': 'invalid_request_error', 'param': 'prompt', 'code': 'max_length_exceeded'}}
```

**DALL-E — 速率限制（生成特有）：**
```
openai.RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for images per minute. Limit: 5 images/min for dall-e-3.', 'type': 'rate_limit_error', 'code': 'rate_limit_exceeded'}}
```

**Imagen — 无效参数：**
```
google.api_core.exceptions.InvalidArgument: 400 Invalid aspect ratio: '3:2'. Supported: 1:1, 3:4, 4:3, 9:16, 16:9
```

### 为什么失败

- 标准 API 错误（由 §10 / §17 处理），但带有生成专属参数
- 生成端点的内容策略违规触发条件与 chat 不同
- 生成端点有独特参数（`size`、`quality`、`style`、`n`、`response_format`）

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **中** | 图片生成应用中常见 |
| 格式稳定性 | **高** | 与 §10 / §17 相同 |
| 实现难度 | **无** | 由 `APIErrorParser`（§10）/ `GeminiErrorParser`（§17）处理 |
| 复现价值 | **中** | 可生成修正后的生成调用 |

### 实现说明

- **无需独立 parser** — 由 §10 / §17 处理
- **新增生成专属元数据**：`api="images"`、`model="dall-e-3"`、`size`、`quality`、`style`

---

## 32. 视频理解错误

### 真实格式

**Gemini — 视频过长：**
```
google.api_core.exceptions.InvalidArgument: 400 Video duration (3h 15m) exceeds maximum supported duration (2h) for model gemini-2.5-flash
```

**Gemini — 视频格式不支持：**
```
google.api_core.exceptions.InvalidArgument: 400 Unsupported video codec: 'hevc'. Supported: h264, vp8, vp9
```

**Gemini — 视频帧提取失败：**
```
google.api_core.exceptions.InternalServerError: 500 Failed to extract frames from video: corrupted video data at offset 45.2MB
```

**Gemini — 视频过大：**
```
google.api_core.exceptions.InvalidArgument: 400 Video file size (5.2GB) exceeds maximum (2GB) for inline upload. Use File API instead.
```

### 为什么失败

- 视频理解是 Gemini 特有功能，有独特约束
- 错误遵循 Google API 格式（§17），但带有视频专属消息
- 视频处理可能在多个阶段失败（上传、编码验证、帧提取、token 计算）

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **低** | 视频理解是较新功能 |
| 格式稳定性 | **高** | Google API 错误格式 |
| 实现难度 | **无** | 由 §17 `GeminiErrorParser` 处理 |
| 复现价值 | **低** | 视频错误通常是数据问题 |

### 实现说明

- **无需独立 parser** — 由 `GeminiErrorParser`（§17）处理
- **新增视频元数据**：`media_type="video"`、`duration`、`codec`、`file_size`

---

## 33. 多模态 token 计算错误

### 真实格式

**OpenAI — 图片 token 溢出：**
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "This model's maximum context length is 128000 tokens. Your messages with images resulted in 150000 tokens. Image tokens are calculated based on resolution: a 1024x1024 image uses approximately 765 tokens.", 'type': 'invalid_request_error', 'param': 'messages', 'code': 'context_length_exceeded'}}
```

**Gemini — 视频 token 溢出：**
```
google.api_core.exceptions.InvalidArgument: 400 Total token count (500000) exceeds model limit (1048576). Video tokens: 1 token per second of video. Your 2-hour video uses approximately 7200 tokens.
```

**Gemini — 混合媒体 token 计算：**
```
google.api_core.exceptions.InvalidArgument: 400 Input contains mixed media types. Total tokens: 250000 (text: 5000, images: 20000, video: 225000). Exceeds model limit of 200000.
```

**Anthropic — 图片 token 限制：**
```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Total input tokens (150000) exceeds maximum (200000). Note: image tokens are calculated based on image dimensions.'}}
```

### 为什么失败

- 多模态 token 计算是提供商特定的：
  - OpenAI：图片 token 基于分辨率（基于 tile 的计算）
  - Gemini：视频 = 1 token/秒，图片 = 基于分辨率，不同模型不同
  - Anthropic：图片 token 基于尺寸
- 错误消息包含 token 分解但以非结构化文本形式
- 标准上下文窗口错误（§13）不捕获媒体专属 token 信息

### 可支持性评估

| 评估维度 | 评级 | 说明 |
|----------|------|------|
| 出现频率 | **中** | 多模态输入场景常见 |
| 格式稳定性 | **中** | Token 计算规则随模型版本变化 |
| 实现难度 | **低** | 扩展 §13 `LLMErrorParser` 增加媒体 token 提取 |
| 复现价值 | **中** | 可生成减少媒体输入以适应上下文的代码 |

### 实现说明

1. **扩展 `LLMErrorParser`（§13）** 解析媒体 token 分解：
   - 从错误消息中提取各媒体类型的 token 数
   - 解析图片/视频/音频专属的 token 计算提示

2. **提取为 `ParsedTrace`**：
   - `error` = `"ContextWindowExceeded: {token_summary}"`
   - 元数据：`text_tokens`、`image_tokens`、`video_tokens`、`audio_tokens`、`media_type`

---

## 汇总表

| # | 格式 | 影响的 Parser 组件 | 复杂度 | 复现价值 | 优先级 |
|---|------|-------------------|--------|----------|--------|
| 1 | SyntaxError 指针 | `_RE_CALL_SITE` + `_parse_single_block` | 中 | 高 | **P1** |
| 2 | ExceptionGroup | 新标题 + `\|` 前缀去除 | 高 | 高 | **P1** |
| 3 | Warning 格式 | 新增 `WarningParser` 类 | 低 | 低 | P3 |
| 4 | RecursionError 深度 | 新正则 + `ParsedTrace` 字段 | 低 | 中 | P3 |
| 5 | Exception notes | 新正则 + `ParsedTrace.notes` | 低 | 中 | P2 |
| 6 | Logging exc_info 前缀 | 放宽 `_RE_TRACEBACK_HEADER` | 低 | 高 | **P1** |
| 7 | Re-raise 标注 | 检测源码行中的裸 `raise` | 低 | 中 | P3 |
| 8 | Doctest 格式 | 去除框架，解析内嵌 traceback | 低 | 低 | P3 |
| 9 | pytest 短回溯 | 无需改动（完整 traceback 已可用） | 无 | 无 | — |
| 10 | LLM API 错误 JSON | 新增 `APIErrorParser` | 低 | 中 | **P1** |
| 11 | MCP JSON-RPC 错误 | 新增 `MCPRpcParser` | 低 | 中 | P2 |
| 12 | LangChain Agent 详细输出 | 新增 `AgentLogParser` | 中 | 高 | P2 |
| 13 | Token/上下文限制 | 新增 `LLMErrorParser` | 低 | 高 | **P1** |
| 14 | Agent 工具截断错误 | 扩展 `AgentLogParser` | 低 | 高 | P2 |
| 15 | SSE 流式错误块 | 扩展 `APIErrorParser` | 低 | 中 | P2 |
| 16 | 图片 / Vision API 错误 | 由 §10 处理 | 无 | 中 | P3 |
| 17 | Google Gemini API 错误 | 扩展 `APIErrorParser` 或新增 `GeminiErrorParser` | 低 | 中 | **P1** |
| 18 | A2A 协议错误 | 扩展 `MCPRpcParser` 增加 A2A 错误码 | 低 | 中 | **P1** |
| 19 | 内容审核/安全过滤 | 扩展 `APIErrorParser` 增加策略检测 | 低 | 中 | P2 |
| 20 | Tool Calling / Function Calling | 扩展 `APIErrorParser` 增加 tool 专属 code | 低 | 高 | P2 |
| 21 | OpenAI Responses API | 扩展 SSE 解析器处理 `response.failed` 信封 | 低 | 中 | P2 |
| 22 | Agent 框架错误 | 新增 `AgentFrameworkParser` | 中 | 高 | P2 |
| 23 | LiteLLM 统一异常 | 扩展 `APIErrorParser` 增加 LiteLLM 异常映射 | 低 | 中 | P2 |
| 24 | Anthropic Extended Thinking | 由 §10 处理 | 无 | 低 | P3 |
| 25 | Embedding API 错误 | 由 §10 处理 | 无 | 中 | P3 |
| 26 | Batch API 错误 | 扩展 `APIErrorParser` 处理 batch 信封 | 低 | 低 | P3 |
| 27 | Realtime API WebSocket | 扩展 `APIErrorParser` 处理 WebSocket 消息 | 低 | 低 | P3 |
| 28 | 音频 API（Whisper/TTS） | 由 §10 处理 | 无 | 中 | P3 |
| 29 | 文档/PDF 输入 | 由 §10 / §17 处理 | 无 | 中 | P3 |
| 30 | Gemini 多模态（视频/音频） | 由 §17 处理 | 无 | 中 | P3 |
| 31 | 图片生成（DALL-E/Imagen） | 由 §10 / §17 处理 | 无 | 中 | P3 |
| 32 | 视频理解 | 由 §17 处理 | 无 | 低 | P3 |
| 33 | 多模态 token 计算 | 扩展 §13 `LLMErrorParser` | 低 | 中 | P3 |

### 建议实施顺序

**阶段 1 — 高影响（P1）：**
1. SyntaxError 指针 — 最常见的 Python 格式 gap
2. Logging exc_info 前缀 — 生产日志中最常见的格式
3. LLM API 错误 JSON — 最常见的 LLM 格式 gap
4. Token/上下文限制 — 高频率，高复现价值
5. Google Gemini API — 第三大提供商，格式独特
6. A2A 协议 — 与 MCP 并列的新兴标准
7. ExceptionGroup — 随 asyncio 普及增长

**阶段 2 — Agent/MCP 生态（P2）：**
8. LangChain Agent 详细输出 + Agent 工具截断错误（合并 parser）
9. Agent 框架错误（CrewAI/AutoGen/ADK/Semantic Kernel）
10. Tool Calling / Function Calling 错误
11. MCP JSON-RPC 错误 + A2A 协议（共享 parser）
12. 内容审核/安全过滤错误
13. LiteLLM 统一异常体系
14. OpenAI Responses API 错误
15. Exception notes
16. SSE 流式错误块

**阶段 3 — 多模态及其他（P3）：**
17. 图片 / Vision API 错误（随 §10 免费实现）
18. 音频 API 错误（随 §10 免费实现）
19. 文档/PDF 输入错误（随 §10 / §17 免费实现）
20. Gemini 多模态错误（随 §17 免费实现）
21. 图片生成错误（随 §10 / §17 免费实现）
22. 视频理解错误（随 §17 免费实现）
23. 多模态 token 计算（扩展 §13）
24. Embedding API 错误（随 §10 免费实现）
25. Anthropic Extended Thinking（随 §10 免费实现）
26. Batch API 错误
27. Realtime API WebSocket 错误
22. RecursionError 深度
23. Warning 格式
24. Re-raise 标注
25. Doctest 格式
