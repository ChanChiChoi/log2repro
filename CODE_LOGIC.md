# log2repro 代码逻辑文档

> 本文档描述项目所有模块的内部逻辑、数据流和函数职责。修改代码时必须同步更新本文档。

---

## 目录

- [1. 架构总览](#1-架构总览)
- [2. 模块依赖图](#2-模块依赖图)
- [3. 核心数据模型](#3-核心数据模型)
- [4. parsers/ — 日志解析层](#4-parsers--日志解析层)
- [5. extractors/ — AST 上下文提取](#5-extractors--ast-上下文提取)
- [6. generators/ — LLM 代码生成](#6-generators--llm-代码生成)
- [7. validators/ — 沙箱验证与自动修复](#7-validators--沙箱验证与自动修复)
- [8. eval_metrics.py — 质量评估指标](#8-eval_metricspy--质量评估指标)
- [9. cli.py — CLI 入口与全链路编排](#9-clipy--cli-入口与全链路编排)
- [10. utils/io.py — 输入输出工具](#10-utilsioy--输入输出工具)
- [11. benchmarks/ — 基准测试框架](#11-benchmarks--基准测试框架)
- [12. 全链路数据流](#12-全链路数据流)

---

## 1. 架构总览

```
输入（日志文本）
    │
    ▼
┌──────────┐    ┌──────────────┐    ┌──────────────┐    ┌───────────────┐    ┌──────────┐
│ parsers  │───▶│ extractors   │───▶│ generators   │───▶│ validators    │───▶│ 输出文件  │
│ 解析日志 │    │ AST 提取     │    │ LLM 生成     │    │ 沙箱+自动修复│    │ 4 个文件  │
└──────────┘    └──────────────┘    └──────────────┘    └───────────────┘    └──────────┘
```

**职责划分：**
- **parsers/**: 正则解析原始日志 → `ParsedTrace`
- **extractors/**: Python `ast` 模块提取源码上下文 → `ASTContext`
- **generators/**: 组装 prompt + 调用 LLM → `dict[str, str]`（文件字典）
- **validators/**: venv 沙箱执行 + 错误分类 + LLM 自动修复循环
- **eval_metrics.py**: 批量评估生成质量（4 个指标）
- **cli.py**: Typer CLI，编排全链路

---

## 2. 模块依赖图

```
cli.py
├── parsers/stacktrace.py
│   └── parsers/base.py (ParsedTrace, BaseParser)
├── extractors/ast_parser.py (ASTContext, extract_ast_context)
├── generators/code_gen.py
│   ├── generators/prompts.py (system prompts, Jinja2 templates)
│   ├── parsers/base.py (ParsedTrace)
│   ├── extractors/ast_parser.py (ASTContext)
│   └── validators/sandbox.py (SandboxResult, run_in_sandbox)
├── validators/auto_fix.py
│   ├── generators/code_gen.py (_call_llm, parse_llm_response)
│   ├── generators/prompts.py (select_system_prompt)
│   └── validators/sandbox.py (SandboxResult, _extract_exc_type)
├── validators/sandbox.py (venv + subprocess)
├── eval_metrics.py
│   ├── generators/code_gen.py (parse_llm_response)
│   └── validators/sandbox.py (run_in_sandbox)
└── utils/io.py (read_input, write_output)
```

---

## 3. 核心数据模型

### `ParsedTrace`（parsers/base.py）

Pydantic BaseModel，表示一条解析后的错误跟踪。

| 字段 | 类型 | 说明 |
|------|------|------|
| `file` | `str` | 错误发生的源文件路径 |
| `line` | `int` | 行号（≥0） |
| `error` | `str` | 错误类型和消息，如 `"ValueError: bad value"` |
| `context_vars` | `list[str]` | 从 traceback 源码行提取的变量名 |
| `chain` | `list[str]` | 调用链，格式 `"file:func:line"` |

方法：`to_context_dict()` → 转为 dict 供下游使用。

### `ASTContext`（extractors/ast_parser.py）

Pydantic BaseModel，表示从源文件 AST 提取的上下文。

| 字段 | 类型 | 说明 |
|------|------|------|
| `signature` | `str` | 出错函数的完整签名 |
| `imports` | `list[str]` | 文件中的 import 语句 |
| `known_vars` | `dict[str, str]` | 变量名 → 类型注解字符串 |

方法：`to_context_dict()` → 转为 dict。

### `ReproContext`（generators/code_gen.py）

dataclass，聚合 `ParsedTrace` + `ASTContext` + model。

| 字段 | 类型 | 说明 |
|------|------|------|
| `trace` | `ParsedTrace` | 解析后的错误信息 |
| `ast_context` | `ASTContext` | AST 提取的上下文（可为空） |
| `model` | `str` | LLM 模型标识，如 `"gpt-4o"` |

方法：`to_prompt_vars()` → 返回 dict 供 Jinja2 渲染。

### `SandboxResult`（validators/sandbox.py）

dataclass，沙箱执行结果。

| 字段 | 类型 | 说明 |
|------|------|------|
| `stdout` | `str` | 标准输出 |
| `stderr` | `str` | 标准错误 |
| `exit_code` | `int` | 进程退出码 |
| `timed_out` | `bool` | 是否超时 |
| `error_reproduced` | `bool` | 是否复现了原始错误 |
| `venv_path` | `str` | 创建的 venv 路径 |
| `pip_ok` | `bool` | pip install 是否成功 |

### `FixResult`（validators/auto_fix.py）

dataclass，自动修复循环的最终结果。

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | `bool` | 是否成功复现 |
| `files` | `dict[str, str]` | 最终文件字典 |
| `rounds_used` | `int` | 使用的修复轮次 |
| `history` | `list[tuple[str, str]]` | 每轮的 `(error_type, snippet)` |
| `suggestions` | `list[str]` | 人工修复建议（降级时） |
| `degraded` | `bool` | 是否降级为 dry-run |

### `SingleEvalResult` / `BatchEvalResult`（eval_metrics.py）

评估结果模型。`BatchEvalResult` 提供聚合属性（`runnable_rate`、`dep_conflict_rate`、`mock_coverage`、`token_efficiency`）和 `report()` 方法。

---

## 4. parsers/ — 日志解析层

### 4.1 base.py

**`ParsedTrace`**: 见 [核心数据模型](#3-核心数据模型)。

**`BaseParser`**: 抽象基类。
- `parse(text) -> list[ParsedTrace]`：抽象方法，子类必须实现。
- `can_parse(text) -> bool`：启发式检查，默认返回 `True`（非空文本）。

### 4.2 stacktrace.py

**`StacktraceParser(BaseParser)`**: Python traceback 解析器。

**正则常量：**
- `_RE_TRACEBACK_HEADER`: 匹配 `Traceback (most recent call last):`
- `_RE_CALL_SITE`: 匹配 `File "path.py", line 42, in func_name`
- `_RE_EXCEPTION_LINE`: 匹配异常行。两个分支：
  - `exc_type`: 带点号的模块路径，如 `ssl.SSLCertVerificationError`
  - `exc_type2`: 裸异常名，要求至少一个小写字母（排除 `DETAIL`、`HINT` 等全大写词）
- `_RE_VAR_PATTERN`: 匹配变量名标识符
- `_STOPWORDS`: 排除的关键词集合（Python 关键字 + 内置函数）

**核心流程 `parse(text)`：**

```
text
  │
  ▼
_split_tracebacks(text)          # 按 "Traceback ..." 分割，处理链式异常
  │                               # 切掉 "During handling ..." 前缀
  ▼
list[str]                        # 每个元素是一个独立的 traceback block
  │
  ▼ (对每个 block)
_parse_single_block(block)
  ├── _RE_CALL_SITE.finditer()   # 提取所有调用点
  ├── 最后一个调用点 = 错误源头   # file + line
  ├── 反向遍历行，匹配异常行      # 跳过缩进行，只匹配非缩进的异常头
  ├── 构建 chain 列表             # "file:func:line" 格式
  └── _extract_context_vars()    # 从源码行提取变量名（排除 stopwords）
  │
  ▼
ParsedTrace
```

**`_extract_context_vars(block, call_sites)`：**
- 遍历 block 中的行
- 跳过调用点行、空行、Traceback 头、异常行
- 对以 4 空格开头的行（Python 显示的源码行），用 `_RE_VAR_PATTERN` 提取变量名
- 排除 `_STOPWORDS` 中的词和长度 ≤1 的词

### 4.3 sentry.py

**`SentryParser(BaseParser)`**: Sentry JSON 解析器（功能完整）。

- `can_parse(text)`: 检查是否以 `{` 开头且包含 `"exception"` / `"stacktrace"` / `"culprit"` 键。
- `parse(text)`: 解析 JSON，优先取 `exception.values`，fallback 到顶层 `stacktrace`。
- `_parse_exception_value(exc_val)`: 从 Sentry frame 提取 `file`、`line`、`error`、`chain`、`context_vars`。

### 4.4 ci_log.py

**`CILogParser(BaseParser)`**: CI 日志解析器（功能完整）。

- `can_parse(text)`: 剥离 ANSI 转义码后委托给 `StacktraceParser.can_parse()`。
- `parse(text)`: 先剥离 ANSI，尝试全文解析；失败则按 CI step 边界（`##[`、`Run `、`Step `、`ERROR`、`FAIL`）分段解析。
- `_split_ci_sections(text)`: 按边界正则分割。

---

## 5. extractors/ — AST 上下文提取

### ast_parser.py

**`ASTContext`**: 见 [核心数据模型](#3-核心数据模型)。

**入口函数：**

`extract_ast_context(source_path, target_line, target_func)` → 读取文件 → 调用 `extract_ast_context_from_source()`。

`extract_ast_context_from_source(source, filename, target_line, target_func)` → 核心实现：

```
source (str)
  │
  ▼
ast.parse(source)                # 解析为 AST 树
  │
  ├── _extract_imports(tree)     # 遍历 Import/ImportFrom 节点
  │     └── list[str]            # ["import os", "from typing import Optional"]
  │
  ├── _extract_global_vars(tree) # 顶层 AnnAssign 节点
  │     └── dict[str, str]       # {"user_id": "Optional[int]"}
  │
  └── _find_target_function(tree, target_line, target_func)
        │
        ├── 优先按 target_func 名称匹配
        ├── fallback: 按 target_line 所在行号范围匹配（取最小函数）
        │
        ▼ (如果找到)
        ├── _build_signature(func_node)   # 构建完整函数签名字符串
        └── _extract_local_vars(func_node) # 函数内 AnnAssign 节点
  │
  ▼
ASTContext(signature, imports, known_vars)
```

**`_build_signature(func_node)`：**
- 处理 `posonlyargs`、`args`、`vararg`、`kwonlyargs`、`kwarg`
- 为每个参数附加类型注解和默认值
- 处理 `async def` 前缀
- 处理返回值注解

**`_unparse_annotation(node)` / `_unparse_node(node)`：**
- 优先用 `ast.unparse()`（Python 3.9+）
- fallback 手动处理 `Name`、`Attribute`、`Subscript`、`Tuple`、`Constant`

---

## 6. generators/ — LLM 代码生成

### 6.1 prompts.py

**系统提示（3 个）：**

| 常量 | 适用场景 | 特点 |
|------|----------|------|
| `SYSTEM_PROMPT_GENERAL` | 通用 Python 错误 | 默认，80 行限制，unittest.mock |
| `SYSTEM_PROMPT_NETWORK` | 网络/IO 错误 | 强制 mock 所有网络调用 |
| `SYSTEM_PROMPT_DATABASE` | 数据库错误 | 强制 mock 所有 DB session |

**`select_system_prompt(error)`：**
- 用 `_NETWORK_KEYWORDS`（`requests.`、`ssl.`、`ConnectionRefused` 等）和 `_DATABASE_KEYWORDS`（`sqlalchemy.`、`IntegrityError` 等）匹配 error 字符串
- 返回对应的系统提示

**用户消息模板 `USER_MESSAGE_TEMPLATE`：**
Jinja2 模板，变量：`file`、`line`、`error`、`chain`、`context_vars`、`signature`、`imports`、`known_vars`。

**`render_user_message(**kwargs)`：** 渲染用户消息模板。

**修正提示模板 `REFINE_PROMPT_TEMPLATE`：**
沙箱反馈循环用，包含：原始错误、沙箱 stderr/stdout、当前 reproduce.py、修复要求。

**`render_refine_message(...)`：** 渲染修正提示。

### 6.2 code_gen.py

**常量：**
- `DEFAULT_TEMPERATURE = 0.2`
- `DEFAULT_MAX_TOKENS = 2000`
- `MAX_RETRIES = 2`（LLM 调用重试次数）
- `RETRY_BACKOFF_BASE = 2.0`（指数退避基数）
- `DEFAULT_SANDBOX_TIMEOUT = 10`
- `DEFAULT_MAX_REFINE_ROUNDS = 2`
- `EXPECTED_FILES = ("reproduce.py", "requirements.txt", "mock_data.json")`
- `_CODE_BLOCK_RE`: 匹配 Markdown 围栏代码块

**`_call_llm(model, messages, temperature, max_tokens)`：**
- 唯一与 `litellm` 交互的函数（隔离便于 mock）
- 调用 `litellm.completion()`，返回响应文本

**`_generate_initial(context, temperature, max_tokens)`：**
- 组装 system prompt + user message
- 调用 `_call_llm()`，解析响应，验证文件完整性
- 失败重试最多 `MAX_RETRIES` 次，指数退避

**`generate_repro_script(context, temperature, max_tokens, sandbox_timeout, max_refine_rounds)`：**

```
context
  │
  ▼
_generate_initial(context)       # 首次 LLM 生成（含重试）
  │
  ▼
files: dict[str, str]            # {"reproduce.py": "...", ...}
  │
  ▼ (如果 max_refine_rounds > 0)
for round in 1..max_refine_rounds:
  │
  ├── _run_sandbox_check(files, context, timeout)
  │     ├── 写入临时目录
  │     └── run_in_sandbox(...) → SandboxResult
  │
  ├── if error_reproduced → return files
  │
  └── _refine_with_sandbox_feedback(context, current_files, sandbox_result)
        ├── render_refine_message(...)     # 构建修正提示
        ├── _call_llm(...)                 # LLM 返回修正代码
        └── merge files                    # 更新 reproduce.py，保留其他文件
  │
  ▼
return files（最终版本）
```

**`parse_llm_response(response_text)`：**
- 用 `_CODE_BLOCK_RE` 提取所有围栏代码块
- `_normalise_block_name(raw)` 映射块名：
  - 已知文件名（`reproduce.py` 等）→ 直接用
  - 语言标签（`python`→`reproduce.py`、`json`→`mock_data.json`、`text`→`requirements.txt`）
  - 含 `.` 的字符串 → 保留为自定义文件名
  - 其他 → 忽略

**`_validate_files(files)`：** 检查 `EXPECTED_FILES` 是否全部存在，否则抛 `ValueError`。

---

## 7. validators/ — 沙箱验证与自动修复

### 7.1 sandbox.py

**网络隔离 `_NO_NET_ENV`：**
```python
{"no_proxy": "*", "NO_PROXY": "*", "http_proxy": "", "HTTP_PROXY": "",
 "https_proxy": "", "HTTPS_PROXY": "", "all_proxy": "", "ALL_PROXY": ""}
```

**`_extract_exc_type(expected_error)`：**
- 从错误字符串提取异常类型名
- 处理冒号分割（`"OSError: [Errno 24]"` → `"OSError"`）
- 处理点号路径（`"ssl.SSLCertVerificationError"` → `"SSLCertVerificationError"`）

**`_check_error_reproduced(stderr, expected_error)`：**
- 提取异常类型名，在 stderr 中搜索

**`_create_venv(venv_dir)`：**
- 调用 `venv.create(venv_dir, with_pip=True, symlinks=True)`
- 返回 `bin/` 目录路径

**`_pip_install(python, requirements, timeout)`：**
- 子进程运行 `python -m pip install -r requirements.txt --quiet`
- 注入 `_NO_NET_ENV` 环境变量
- 返回 `(success, error_message)`

**`run_in_sandbox(script_path, requirements_path, timeout, expected_error)`：**

```
script_path
  │
  ├── 检查文件存在
  │
  ▼
tempfile.TemporaryDirectory
  │
  ├── _create_venv(venv_dir)         # 创建 venv（with_pip=True）
  ├── _pip_install(python, req_path) # 安装依赖（如果提供）
  │
  ▼
subprocess.run([python, script_path])
  ├── capture_output=True
  ├── timeout=timeout
  ├── cwd=script_path.parent
  ├── env=_sandbox_env()             # 注入网络隔离环境变量
  │
  ▼ (异常处理)
TimeoutExpired → timed_out=True, exit_code=-1
  │
  ▼
_check_error_reproduced(stderr, expected_error)
  │
  ▼
SandboxResult
```

### 7.2 auto_fix.py

**可修复错误类型 `_FIXABLE_ERRORS`：**
`SyntaxError`、`IndentationError`、`TabError`、`ModuleNotFoundError`、`ImportError`、`NameError`、`AttributeError`、`TypeError`、`FileNotFoundError`

**`_classify_error(stderr)`：**
- 反向遍历 stderr 行，查找 `_FIXABLE_ERRORS` 中的错误类型
- 返回错误类型名或 `None`

**`_extract_error_snippet(stderr, max_lines)`：** 取 stderr 最后 N 行。

**`_build_fix_suggestions(error_type, stderr)`：**
根据错误类型生成人工修复建议：
- `ModuleNotFoundError` → 提取模块名，建议添加依赖或 mock
- `SyntaxError` → 提取行号，建议检查缩进
- `NameError` → 提取变量名，建议声明或 mock
- `ImportError` → 建议检查版本兼容性
- `AttributeError` → 提取属性名
- `TypeError` → 提取参数错误信息
- `FileNotFoundError` → 建议检查 mock_data.json

**`_build_fix_messages(error_type, stderr, current_code, round_idx, original_error)`：**
- 用 `_FIX_PROMPT_TEMPLATE` 渲染 LLM 提示
- 每轮缩小修复范围（只修复当前错误类型）

**`auto_fix_loop(context_model, original_error, initial_files, sandbox_fn, temperature, max_tokens)`：**

```
initial_files
  │
  ▼
for round in 1..MAX_FIX_ROUNDS (3):
  │
  ├── sandbox_fn(files) → SandboxResult
  │
  ├── if error_reproduced → return FixResult(success=True)
  │
  ├── if not pip_ok → return FixResult(degraded=True, suggestions=[...])
  │
  ├── _classify_error(stderr)
  │     ├── None (非修复错误) → return FixResult(degraded=True)
  │     └── error_type (可修复) → 继续
  │
  ├── _build_fix_messages(...) → LLM 提示
  ├── _call_llm(...) → 修正后的代码
  └── parse_llm_response(...) → 更新 files
  │
  ▼ (轮数耗尽)
return FixResult(degraded=True, suggestions=_build_fix_suggestions(...))
```

---

## 8. eval_metrics.py — 质量评估指标

### 数据模型

**`GenerationInput`**：评估输入（trace_name、files、tokens_used、expected_error）。

**`SingleEvalResult`**：单次评估结果（runnable、dep_conflict、mock_coverage、error_reproduced 等）。

**`BatchEvalResult`**：批量评估结果，提供聚合属性和 `report()` 方法。

### 4 个指标函数

**`check_runnable(files, timeout)` → `(bool, str)`：**
- 写入临时目录，sandbox 执行
- exit_code=0 → 可运行
- stderr 包含 `ModuleNotFoundError`/`ImportError`/`SyntaxError`/`NameError`/`AttributeError` → 不可运行
- 其他错误（应用级异常）→ 可运行
- 超时 → 可运行（非代码错误）

**`check_dep_conflict(requirements_text)` → `(bool, str)`：**
- 用 `_REQ_LINE_RE` 逐行解析
- 检测不可解析行和同包不同版本约束

**`check_mock_coverage(repro_code)` → `(float, list[str])`：**
- 用 `_REAL_CALL_PATTERNS` 扫描真实调用（`requests.get(`、`sqlite3.connect(` 等）
- 检查是否使用了 `unittest.mock`
- 对每个真实调用，向上扫描是否在 `with patch(...)` 块内
- 计算覆盖率 = 1 - unmocked / total

**`evaluate_single(gen, sandbox_timeout)` → `SingleEvalResult`：**
依次调用 4 个指标函数。

**`evaluate_batch(inputs, sandbox_timeout)` → `BatchEvalResult`：**
批量调用 `evaluate_single`。

### 报告

`BatchEvalResult.report()` 生成 Markdown 表格，包含指标汇总和问题明细。

---

## 9. cli.py — CLI 入口与全链路编排

**CLI 框架：** Typer + Rich

**命令 `log2repro run`：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `input_source` | Argument | 文件路径 / `-`（stdin）/ 原始文本 |
| `--model` / `-m` | Option | LLM 模型（默认 `gpt-4o`） |
| `--dry-run` / `-n` | Option | 仅解析，跳过 LLM |
| `--output-dir` / `-d` | Option | 输出目录（默认 `./repro_out`） |
| `--output` / `-o` | Option | JSON 输出文件（legacy） |
| `--sandbox-timeout` | Option | 沙箱超时（默认 10s） |
| `--max-refine` | Option | 最大修正轮次（默认 2） |
| `--verbose` / `-v` | Option | 详细日志 |

**全链路流程 `run()`：**

```
input_source
  │
  ├── read_input(input_source)           # utils/io.py
  │
  ▼
StacktraceParser.parse(raw_text)         # 解析 traceback
  │
  ├── _try_extract_ast(file, line, chain) # AST 提取（best-effort）
  │
  ├── if dry_run → _print_dry_run()      # 输出 JSON 到控制台
  │
  ▼
_run_full_pipeline(...)
  │
  ├── ReproContext(trace, ast_context, model)
  │
  ├── generate_repro_script(ctx)          # generators/code_gen.py
  │     └── 首次生成 + 沙箱验证 + 修正循环
  │
  ├── auto_fix_loop(...)                  # validators/auto_fix.py
  │     └── 语法/导入错误 → LLM 修复 → 最多 3 轮 → 降级建议
  │
  ├── _generate_readme(trace, fix_result, model)
  │     └── 生成 README_repro.md（错误信息 + 调用链 + 使用方法 + 修复历史）
  │
  └── _write_to_dir(output_dir, files, trace)
        └── 写入 reproduce.py, requirements.txt, mock_data.json, README_repro.md
```

**`_try_extract_ast(file_path, target_line, chain)`：**
- 检查文件存在
- 从 chain 中推断函数名
- 调用 `extract_ast_context_from_source()`
- 失败返回 `None`

**`_generate_readme(trace, fix_result, model)`：**
生成 Markdown README，包含：
- 原始错误信息（文件、行号、错误）
- 调用链
- 复现状态（成功/失败）
- 使用方法（pip install + python reproduce.py）
- 自动修复历史表格
- 人工修复建议（降级时）

**命令 `log2repro version`：** 打印版本号。

---

## 10. utils/io.py — 输入输出工具

**`_looks_like_path(source)`：**
- 包含 `/` 且不以 `Traceback` 开头 → 看起来像路径
- 以 `.log`/`.txt`/`.out`/`.err`/`.py`/`.json` 结尾 → 看起来像路径

**`read_input(source)`：**
1. `"-"` 或 `"/dev/stdin"` → 读 stdin
2. 文件存在 → 读文件
3. 不含换行符且看起来像路径 → 抛 `FileNotFoundError`
4. 否则 → 当作原始文本返回

**`write_output(data, output_path)`：**
- 有路径 → 创建父目录 + 写文件
- 无路径 → print 到 stdout

---

## 11. benchmarks/ — 基准测试框架

### prompt_variants.py

5 个 prompt 变体：

| 变体 | 侧重 | 特点 |
|------|------|------|
| P1_SPEED | 速度 | 精简指令、30 行限制 |
| P2_MINIMAL | 最小 | 3 行规则、无示例 |
| P3_BALANCED | 平衡 | 默认 prompt |
| P4_COMPLETE | 完整 | 含 few-shot 示例 |
| P5_SECURITY | 安全 | 强制审查模式、禁用 eval/exec |

### mock_responses.py

确定性 mock 响应生成：
- 用 hash 种子控制随机性
- 按 prompt 变体分层质量（P1 短响应偶遗漏、P3 中等偶尔幻觉、P5 最长零幻觉偶不触发）

### validator.py

**`validate_response(response_text, trace)` → `ValidationResult`：**
- `triggers_error`: 代码中是否包含原始异常类型或 `raise`
- `hallucinated`: 是否引用了未知库（不在 `_STDLIB_MODULES` + `_KNOWN_PACKAGES` 中）
- `all_files_present`: 3 个文件是否齐全

### runner.py

**`run_benchmark(num_runs)`：**
- 解析 5 个 fixture trace
- 遍历 5 个 prompt 变体 × 5 个 trace × num_runs
- 累计 trigger_count、hallucination_count、total_tokens、file_completeness_count

### report.py

**`VariantResult`**：聚合结果（trigger_rate、hallucination_rate、avg_tokens、file_completeness_rate）。

**`generate_report(results)` / `generate_per_trace_table(trace_results)`**：生成 Markdown 表格。

---

## 12. 全链路数据流

```
输入: "Traceback (most recent call last):
         File "app.py", line 10, in process
           result = api.fetch(user_id)
       ConnectionError: Connection refused"
  │
  ▼
[StacktraceParser.parse]
  │
  ▼
ParsedTrace(
  file="app.py", line=10,
  error="ConnectionError: Connection refused",
  context_vars=["result", "api", "fetch", "user_id"],
  chain=["app.py:process:10"]
)
  │
  ▼
[_try_extract_ast] → ASTContext(signature="def process(user_id: int)", imports=["import requests"], ...)
  │
  ▼
[ReproContext(trace=..., ast_context=..., model="gpt-4o")]
  │
  ▼
[generate_repro_script]
  ├── select_system_prompt("ConnectionError") → SYSTEM_PROMPT_NETWORK
  ├── render_user_message(...) → 用户消息
  ├── _call_llm(model, messages) → LLM 响应
  ├── parse_llm_response(raw_text) → {"reproduce.py": "...", "requirements.txt": "...", "mock_data.json": "..."}
  ├── _validate_files(files) → 通过
  │
  ▼ (沙箱验证循环)
  ├── _run_sandbox_check(files, ctx, timeout=10)
  │     └── run_in_sandbox(...) → SandboxResult(error_reproduced=True?)
  │
  ├── if not reproduced → _refine_with_sandbox_feedback(...)
  │     └── _call_llm(refine_messages) → 修正后的 files
  │
  ▼
files: dict[str, str]
  │
  ▼
[auto_fix_loop]
  ├── sandbox_fn(files) → SandboxResult
  ├── _classify_error(stderr) → "SyntaxError" / None
  ├── if fixable → _call_llm(fix_messages) → 修正 files
  └── 最终 FixResult(success/degraded, files, suggestions)
  │
  ▼
[输出文件]
  ├── reproduce.py        — 最小复现脚本
  ├── requirements.txt    — 依赖清单
  ├── mock_data.json      — Mock 数据
  └── README_repro.md     — 使用说明 + 修复历史
```

---

## 修改代码时的同步检查清单

修改任何模块后，检查以下项目：

1. **数据模型变更** → 更新本文档 [第 3 节](#3-核心数据模型)
2. **函数签名变更** → 更新对应模块章节的函数描述
3. **新增模块** → 更新 [依赖图](#2-模块依赖图) 和新增章节
4. **pipeline 流程变更** → 更新 [全链路数据流](#12-全链路数据流)
5. **新增 CLI 参数** → 更新 [第 9 节](#9-clipy--cli-入口与全链路编排) 的参数表
6. **新增正则/常量** → 更新对应模块的常量说明
7. **新增评估指标** → 更新 [第 8 节](#8-eval_metricspy--质量评估指标)
