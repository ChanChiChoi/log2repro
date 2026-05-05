# 架构

## 系统概览

log2repro 通过 5 阶段流水线将错误日志转换为可运行的复现脚本：

```
┌──────────┐    ┌──────────────┐    ┌──────────────┐    ┌───────────────┐    ┌──────────┐
│  阶段 1  │    │    阶段 2    │    │    阶段 3    │    │     阶段 4    │    │  阶段 5  │
│  解析    │───▶│  AST 提取    │───│  LLM 生成    │───▶│  沙箱 + 修复  │───▶│   输出   │
│ (正则)   │    │ (ast 模块)   │    │  (litellm)   │    │ (venv+subproc)│    │ (4 文件) │
└──────────┘    └──────────────┘    └──────────────┘    └───────────────┘    └──────────┘
```

## 模块地图

```
src/log2repro/
├── cli.py              # 入口 + 流水线编排
├── eval_metrics.py     # 质量评估（4 个指标）
├── parsers/
│   ├── base.py         # ParsedTrace 模型 + BaseParser 抽象类
│   ├── stacktrace.py   # Python traceback 解析器（正则）
│   ├── sentry.py       # Sentry JSON 解析器
│   └── ci_log.py       # CI 日志解析器（ANSI 剥离）
├── extractors/
│   └── ast_parser.py   # AST 上下文提取
├── generators/
│   ├── prompts.py      # 系统提示 + Jinja2 模板
│   └── code_gen.py     # LLM 生成 + 沙箱反馈
├── validators/
│   ├── sandbox.py      # venv + 子进程执行
│   └── auto_fix.py     # 自动修复链（分类 → 修复 → 降级）
└── utils/
    └── io.py           # 输入读取（文件/stdin/原始文本）
```

## 设计决策

### 1. LLM 入口点隔离

`code_gen.py` 中的 `_call_llm()` 是**唯一**与 `litellm` 交互的函数。这使得整个生成流水线可以通过 mock 进行测试，无需真实 LLM。

### 2. 正则而非语法解析

Python traceback 有规范但非正式的格式。正则比完整解析器更简单、更快，且能处理大多数真实场景。边界情况（特殊格式、深层嵌套链式异常）通过多正则模式和反向扫描启发式处理。

### 3. AST 提供约束，LLM 负责生成

AST 提取提供**硬约束**（真实变量名、实际 import、函数签名），防止 LLM 捏造不存在的库或变量。LLM 负责创造性部分（构建 mock、组装脚本）。

### 4. 输出前必须沙箱验证

每个生成的脚本在返回给用户之前，都会在隔离的 venv 中运行（禁用网络）。这可以捕获：
- 导入错误（缺失依赖）
- 语法错误
- 非目标错误的运行时异常

### 5. 优雅降级

如果自动修复循环在 3 轮后失败，系统会输出人类可读的修复建议，而不是静默失败。确保用户始终获得可操作的输出。

### 6. 通过环境变量隔离网络

不使用 OS 级防火墙或 Docker，而是通过环境变量（`NO_PROXY=*`、清空代理变量）实现网络隔离。这种方式可移植、可测试，且足以防止 `requests`/`httpx`/`urllib` 意外发起真实 API 调用。

## 数据流

### 阶段 1：解析

**输入：** 原始文本（文件、stdin 或字符串）

**输出：** `list[ParsedTrace]`

- `StacktraceParser` 按 `Traceback (most recent call last):` 分割
- 处理链式异常（`During handling...`）
- 提取：文件、行号、错误类型+消息、调用链、上下文变量

### 阶段 2：AST 提取

**输入：** `ParsedTrace`（提供文件路径、行号、函数名）

**输出：** `ASTContext`

- 读取源文件（如果可访问）
- 使用 Python `ast` 模块提取：
  - 函数签名（含类型注解和默认值）
  - Import 语句
  - 带注解的变量（全局 + 局部）
- 如果文件不存在或无法解析，优雅降级

### 阶段 3：LLM 生成

**输入：** `ReproContext`（trace + AST + model）

**输出：** `dict[str, str]`（文件名 → 内容）

1. `select_system_prompt()` 选择合适的系统提示（通用/网络/数据库）
2. `render_user_message()` 用 Jinja2 渲染用户消息模板
3. `_call_llm()` 调用 LLM
4. `parse_llm_response()` 提取围栏代码块
5. `_validate_files()` 检查 3 个必需文件是否齐全
6. 失败时：最多重试 2 次，指数退避

### 阶段 4：沙箱 + 修复

**输入：** 生成的文件 + 原始错误

**输出：** 验证/修复后的文件

1. `run_in_sandbox()`：
   - 创建临时 venv
   - 运行 `pip install -r requirements.txt`
   - 执行 `reproduce.py`（网络隔离）
   - 检查 stderr 中是否出现原始错误

2. 如果未复现，将 stderr 反馈给 LLM 进行修正（最多 2 轮）

3. `auto_fix_loop()`：
   - 分类错误（SyntaxError、ImportError 等）
   - 如果可修复：定向 LLM 修复（最多 3 轮）
   - 如果不可修复：返回修复建议
   - 如果耗尽：降级为 dry-run + 建议

### 阶段 5：输出

**输入：** 最终文件 + trace 信息

**输出：** 输出目录中的 4 个文件

| 文件 | 内容 |
|------|------|
| `reproduce.py` | 最小复现脚本 |
| `requirements.txt` | pip 依赖 |
| `mock_data.json` | 测试夹具 / mock 数据 |
| `README_repro.md` | 使用说明 + 修复历史 |

## 依赖关系图

```
cli.py
├── parsers/stacktrace.py ──▶ parsers/base.py
├── extractors/ast_parser.py
├── generators/code_gen.py
│   ├── generators/prompts.py
│   ├── parsers/base.py
│   └── validators/sandbox.py
├── validators/auto_fix.py
│   ├── generators/code_gen.py
│   ├── generators/prompts.py
│   └── validators/sandbox.py
├── validators/sandbox.py
├── eval_metrics.py
│   ├── generators/code_gen.py
│   └── validators/sandbox.py
└── utils/io.py
```

## 测试策略

- **单元测试：** 每个模块有独立的测试文件
- **Mock LLM：** 所有 LLM 调用通过 `_call_llm()`，易于 mock
- **真实子进程：** 沙箱测试在 venv 中运行真实 Python 脚本
- **Trace 夹具：** 30+ 真实错误 trace 覆盖边界情况
- **基准框架：** 5 个 prompt 变体 × 5 个 trace × N 次运行
