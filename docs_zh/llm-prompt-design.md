# LLM 提示设计

## 概述

log2repro 使用结构化的提示策略引导 LLM 生成准确的复现脚本。设计重点是**用 AST 提供硬约束**防止幻觉，以及**定向修正**修复沙箱失败。

## 系统提示

根据错误类型选择三个专用系统提示：

### SYSTEM_PROMPT_GENERAL

**大多数 Python 错误的默认提示。**

核心约束：
- 输出恰好 3 个文件：`reproduce.py`、`requirements.txt`、`mock_data.json`
- 对所有外部调用使用 `unittest.mock`
- 脚本必须独立运行（≤80 行）
- 在预期错误时以非零退出码退出
- 不访问真实网络、数据库或文件系统

### SYSTEM_PROMPT_NETWORK

**用于网络/IO 错误**（`requests.ConnectionError`、`ssl.SSLCertVerificationError`、`httpx.TimeoutException` 等）

额外约束：
- Mock 所有网络调用（`requests.get`、`httpx.AsyncClient`、`urllib.request` 等）
- 使用 `unittest.mock.patch` 作为上下文管理器
- 不打开真实 socket

### SYSTEM_PROMPT_DATABASE

**用于数据库错误**（`sqlalchemy.exc.NoResultFound`、`psycopg2.Error`、`sqlite3.OperationalError` 等）

额外约束：
- Mock 所有数据库 session 和连接
- 对 ORM 查询链使用 `MagicMock`
- 不连接真实数据库

### 选择逻辑

```python
def select_system_prompt(error: str) -> str:
    if any(kw in error for kw in _NETWORK_KEYWORDS):
        return SYSTEM_PROMPT_NETWORK
    if any(kw in error for kw in _DATABASE_KEYWORDS):
        return SYSTEM_PROMPT_DATABASE
    return SYSTEM_PROMPT_GENERAL
```

**网络关键词：** `requests.`、`httpx.`、`aiohttp.`、`ssl.`、`ConnectionRefused`、`ConnectionError`、`Timeout`、`urllib`、`socket.`、`http.client`

**数据库关键词：** `sqlalchemy.`、`psycopg2.`、`sqlite3.`、`pymysql.`、`asyncpg.`、`IntegrityError`、`OperationalError`、`NoResultFound`

## 用户消息模板

使用 Jinja2 模板将结构化上下文注入用户消息：

```jinja2
## 错误信息
- **文件:** `{{ file }}`
- **行号:** {{ line }}
- **错误:** {{ error }}

## 调用链{% for entry in chain %}
- `{{ entry }}`{% endfor %}

## 上下文变量{% for var in context_vars %}
- `{{ var }}`{% endfor %}

## 函数签名
```python
{{ signature }}
```

## 作用域中的 Import{% for imp in imports %}
- `{{ imp }}`{% endfor %}

## 已知变量类型{% for name, type_ in known_vars.items() %}
- `{{ name }}`: `{{ type_ }}`{% endfor %}
```

### 模板变量

| 变量 | 来源 | 用途 |
|------|------|------|
| `file` | `ParsedTrace.file` | 错误位置 |
| `line` | `ParsedTrace.line` | 错误位置 |
| `error` | `ParsedTrace.error` | 错误类型 + 消息 |
| `chain` | `ParsedTrace.chain` | 完整调用栈 |
| `context_vars` | `ParsedTrace.context_vars` | traceback 中的变量名 |
| `signature` | `ASTContext.signature` | 带类型的函数签名 |
| `imports` | `ASTContext.imports` | 源文件中的 import 语句 |
| `known_vars` | `ASTContext.known_vars` | 带类型注解的变量 |

## AST 上下文注入

### 为什么需要 AST？

没有 AST 上下文时，LLM 会捏造：
- 不存在的库（如只用了 `json` 却生成 `import pandas`）
- 错误的函数签名（如缺少参数）
- 不正确的变量名

AST 提取提供**硬约束**，将 LLM 输出锚定在真实代码上。

### AST 提供什么

1. **函数签名** — 准确的参数名、类型、默认值
2. **Import 语句** — 仅源文件中的真实 import
3. **带注解的变量** — 真实变量名和类型提示

### 示例

给定源代码：

```python
from typing import Optional
import requests

USER_API = "https://api.example.com/users"

def fetch_user(user_id: int, timeout: float = 5.0) -> Optional[dict]:
    response = requests.get(f"{USER_API}/{user_id}", timeout=timeout)
    return response.json()
```

AST 提取：
- **签名：** `def fetch_user(user_id: int, timeout: float = 5.0) -> Optional[dict]`
- **Import：** `["from typing import Optional", "import requests"]`
- **已知变量：** `{"USER_API": "str"}`

LLM 随后生成使用 `fetch_user`、`user_id`、`timeout` 和 `requests` 的脚本——而非捏造的替代品。

## 修正提示

当沙箱验证失败时，向 LLM 发送修正提示：

```jinja2
之前生成的 reproduce.py 未能复现原始错误。

## 原始错误
- **异常类型:** {{ original_error }}
- **文件:** {{ file }}:{{ line }}

## 沙箱执行结果
- **退出码:** {{ exit_code }}
- **stderr:**
{{ stderr }}

## 当前 reproduce.py
```python
{{ current_code }}
```

## 要求
1. 只修改导致问题的代码，不要重写整个脚本
2. 分析 stderr 中的新报错，定位根因
3. 确保修改后仍能复现原始异常类型 `{{ exc_type }}`
4. 输出完整的修正后 reproduce.py
```

### 修正策略

修正不是重新生成，而是**定向修复**：
- 只修改有问题的代码
- 必须仍能复现原始错误类型
- LLM 可以看到精确的 stderr 输出进行诊断

## 自动修复提示

对于沙箱修正后仍存在的错误，使用修复提示：

```jinja2
reproduce 脚本存在 {{ error_type }} 需要修复。

## 错误详情
{{ stderr_snippet }}

## 当前 reproduce.py
```python
{{ current_code }}
```

## 修复指令
{{ fix_instructions }}

输出完整的修复后 reproduce.py。
```

### 错误类型对应的修复指令

| 错误类型 | 修复指令 |
|----------|----------|
| `SyntaxError` | 检查缩进、缺少冒号、括号不匹配 |
| `ModuleNotFoundError` | 添加到 requirements.txt 或使用 unittest.mock |
| `ImportError` | 检查模块是否存在及版本兼容性 |
| `NameError` | 确保变量在使用前已定义 |
| `AttributeError` | 检查对象类型和可用方法 |
| `TypeError` | 检查函数签名和参数类型 |
| `FileNotFoundError` | 使用 mock_data.json 或创建临时文件 |

## 反幻觉措施

### 1. AST 锚定

真实变量名和 import 约束 LLM 只使用源代码中存在的内容。

### 2. 文件验证

`_validate_files()` 检查 3 个必需文件是否齐全。缺失文件会触发重试并附带明确指令。

### 3. 沙箱验证

每个生成的脚本都在真实 venv 中运行。导入错误和语法错误在输出前被捕获。

### 4. 自动修复循环

对可修复错误最多进行 3 轮定向修复，并优雅降级为人类可读建议。

## Prompt 变体（基准测试）

`benchmarks/prompt_variants.py` 模块定义了 5 个变体用于对比：

| 变体 | 策略 | 行数限制 | 说明 |
|------|------|----------|------|
| P1_SPEED | 最小指令 | 30 | 最快，可能遗漏边界情况 |
| P2_MINIMAL | 仅 3 条核心规则 | 50 | 无示例 |
| P3_BALANCED | 默认提示 | 80 | 生产默认 |
| P4_COMPLETE | 含 few-shot 示例 | 100 | 最高质量，最多 token |
| P5_SECURITY | 审计模式 | 80 | 显式安全检查 |

运行基准测试进行对比：

```bash
uv run python -m benchmarks.runner
```

## Token 用量

各阶段的典型 token 消耗：

| 阶段 | Token（约） |
|------|-------------|
| 系统提示 | 200-400 |
| 用户消息 | 300-600 |
| LLM 响应 | 800-1500 |
| 修正（每轮） | 1000-2000 |
| 自动修复（每轮） | 800-1500 |
| **总计（无修复）** | **~2000-3000** |
| **总计（含修复）** | **~6000-10000** |
