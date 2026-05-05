# log2repro

**错误日志 → 可运行的复现代码生成器。**

> **[English](README.md)** | **[中文文档](docs_zh/index.md)**

粘贴一段 Python traceback，即可获得一个独立的 `reproduce.py`，能触发原始错误——附带 `requirements.txt`、mock 数据和验证说明。

> 平均复现时间：**45 分钟 → 3 分钟**。

## 为什么需要？

工程师 60% 以上的调试时间花在"猜参数、翻数据库、mock 第三方 API"上。Sentry 告诉你错误*发生在哪里*；log2repro 给你一个*可重放的现场*。

| | Sentry | log2repro |
|---|---|---|
| **输出** | 堆栈跟踪、面包屑、用户上下文 | `reproduce.py` + `requirements.txt` + mock 数据 |
| **集成方式** | 需要 SDK / 代码改动 | 零侵入：粘贴文本、CI 日志或文件 |
| **解决的问题** | 监控 → 发现 → 定位 | 定位 → 构造环境 → 验证修复 |

## 特性

- **AST 驱动的上下文提取** — 从源码中提取真实变量名、函数签名和 import，约束 LLM 输出（不捏造库）
- **沙箱验证** — 在隔离的 venv 中运行生成的代码（禁用网络），验证原始错误是否真正复现
- **自动修复循环** — 如果脚本失败（SyntaxError、ModuleNotFoundError 等），将错误反馈给 LLM 进行定向修复（最多 3 轮）
- **优雅降级** — 3 次修复失败后，输出人类可读的修复建议，而不是静默失败
- **多格式支持** — Python traceback、链式异常、异步错误、C 扩展错误、动态导入
- **LLM 无关** — 使用 [litellm](https://github.com/BerriAI/litellm)，支持 OpenAI、Anthropic、本地模型等

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

## 快速开始

```bash
# 完整流水线：解析 → 生成 → 沙箱 → 自动修复 → 输出
log2repro run error.log --output-dir ./repro_out

# 从 stdin 读取
cat error.log | log2repro run - --output-dir ./repro_out

# 直接粘贴
log2repro run 'Traceback (most recent call last):
  File "app.py", line 10, in process
    result = api.fetch(user_id)
requests.exceptions.ConnectionError: Connection refused'

# 仅解析（不调用 LLM）
log2repro run error.log --dry-run
```

### 输出

```
repro_out/
├── reproduce.py        # 触发原始错误的最小脚本
├── requirements.txt    # pip 依赖
├── mock_data.json      # 测试夹具 / mock 数据
└── README_repro.md     # 使用说明 + 自动修复历史
```

### 示例 `reproduce.py`

```python
"""ConnectionError 的最小复现。"""
from unittest.mock import patch, MagicMock

def test_api_connection():
    with patch("requests.get") as mock_get:
        mock_get.side_effect = ConnectionError("Connection refused")
        import requests
        requests.get("http://api/users/123")  # 抛出 ConnectionError

if __name__ == "__main__":
    test_api_connection()
```

## 用法

```bash
log2repro run <input> [OPTIONS]

参数:
  input                文件路径、"-" 表示 stdin，或原始 traceback 文本

选项:
  -m, --model TEXT     LLM 模型（默认: gpt-4o）
  -n, --dry-run        仅解析，跳过 LLM 生成
  -d, --output-dir     输出目录（默认: ./repro_out）
  -o, --output         将 JSON 写入文件（旧模式）
  --sandbox-timeout    沙箱执行最大秒数（默认: 10）
  --max-refine         沙箱→LLM 最大修正轮次（默认: 2）
  -v, --verbose        启用详细日志
```

## 工作原理

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌───────────────┐
│   解析日志  │────▶│  AST 提取    │────▶│  LLM 生成    │────▶│  沙箱验证     │
│   (正则)    │     │ (ast 模块)   │     │  (litellm)   │     │(venv+子进程)  │
└─────────────┘     └──────────────┘     └──────────────┘     └───────┬───────┘
                                                                      │
                                                    ┌─────────────────┼─────────────────┐
                                                    │ 已复现？        │ 可修复的错误？   │
                                                    ▼                 ▼                  ▼
                                                ✅ 完成          LLM 修复 (×3)     降级 +
                                                                          │         修复建议
                                                                          ▼
                                                                    重新沙箱验证
```

1. **解析** — 基于正则的解析器从 traceback 中提取文件、行号、错误类型、调用链
2. **AST 提取** — Python `ast` 模块从源码中提取真实变量名、函数签名、import
3. **LLM 生成** — 将结构化提示（错误 + AST 上下文）发送给 LLM，解析 Markdown 代码块
4. **沙箱验证** — 创建 venv，安装依赖，禁用网络运行脚本，检查 stderr 中是否出现原始错误
5. **自动修复** — 如果沙箱因可修复错误（SyntaxError、ImportError 等）失败，将 stderr 反馈给 LLM 进行定向修复

## 文档

完整文档请参阅 [docs_zh/index.md](docs_zh/index.md)：

| 章节 | 说明 |
|------|------|
| [快速开始](docs_zh/getting-started.md) | 安装、首次复现、配置 |
| [用户指南](docs_zh/user-guide.md) | CLI 参考、输入格式、输出结构 |
| [架构](docs_zh/architecture.md) | 5 阶段流水线、模块图、设计决策 |
| [解析器参考](docs_zh/parser-reference.md) | 支持的日志格式、正则规则、边界情况 |
| [LLM 提示设计](docs_zh/llm-prompt-design.md) | 系统提示、AST 注入、修正策略 |
| [评估指南](docs_zh/evaluation.md) | 4 个质量指标、基准测试框架 |
| [贡献指南](docs_zh/contributing.md) | 开发环境、测试规范、代码风格 |
| [更新日志](docs_zh/changelog.md) | 版本历史 |
| [路线图](docs_zh/roadmap.md) | 里程碑与规划中的功能 |

## 支持的错误格式

| 类别 | 示例 |
|------|------|
| Python traceback | `ValueError`、`KeyError`、`TypeError`、`AttributeError` |
| 链式异常 | `During handling of the above exception...` |
| 异步错误 | `TaskGroup`、`asyncio.TimeoutError`、异步生成器 |
| C 扩展 | `numpy._UFuncNoLoopError`、`sqlite3.OperationalError`、`struct.error` |
| 动态导入 | `importlib`、`__import__`、懒加载、模块重载 |
| 深层调用栈 | 装饰器、中间件、递归、上下文管理器、回调 |
| 网络/数据库 | `requests`、`httpx`、`aiohttp`、`sqlalchemy`、`psycopg2` |

## 评估指标

```python
from log2repro.eval_metrics import evaluate_batch, GenerationInput

batch = evaluate_batch([
    GenerationInput(trace_name="api_500", files=files, tokens_used=800, expected_error="ValueError: x"),
])
print(batch.report())
```

| 指标 | 说明 |
|------|------|
| **代码可运行率** ↑ | 脚本执行无 ImportError/SyntaxError |
| **依赖冲突率** ↓ | requirements.txt 无版本冲突 |
| **Mock 覆盖率** ↑ | 外部调用（网络、数据库）被正确 mock |
| **Token 效率** ↑ | 每 1,000 token 复现的错误数 |

## 开发

```bash
# 环境搭建
git clone https://github.com/ChanChiChoi/log2repro.git
cd log2repro
uv sync --group dev

# 运行测试（385 个测试，约 2.5 分钟）
uv run pytest -v

# 运行基准测试
uv run python -m benchmarks.runner

# 代码检查
uv run ruff check src/ tests/
```

### 项目结构

```
log2repro/
├── src/log2repro/
│   ├── cli.py              # Typer CLI 入口
│   ├── eval_metrics.py     # 4 个质量指标（可运行、依赖、mock、token）
│   ├── parsers/
│   │   ├── base.py         # ParsedTrace 模型 + BaseParser 抽象类
│   │   ├── stacktrace.py   # Python traceback 解析器（正则）
│   │   ├── sentry.py       # Sentry JSON 解析器
│   │   └── ci_log.py       # CI 日志解析器
│   ├── extractors/
│   │   └── ast_parser.py   # AST 上下文提取（签名、import、变量）
│   ├── generators/
│   │   ├── prompts.py      # 系统提示（通用/网络/数据库）+ 模板
│   │   └── code_gen.py     # LLM 生成 + 沙箱反馈循环
│   ├── validators/
│   │   ├── sandbox.py      # venv + 子进程沙箱，网络隔离
│   │   └── auto_fix.py     # 自动修复链（分类 → LLM 修复 → 降级）
│   └── utils/
│       └── io.py           # 输入读取（文件/stdin/原始字符串）
├── tests/
│   ├── fixtures/            # 30+ 真实错误 trace 样本
│   └── test_*.py            # 385 个测试
└── benchmarks/
    ├── prompt_variants.py   # 5 个 prompt 变体用于对比
    ├── runner.py            # 基准测试执行引擎
    └── validator.py         # 幻觉 + 触发检测
```

## 致谢

- [litellm](https://github.com/BerriAI/litellm) — 统一 LLM API
- [Typer](https://github.com/tiangolo/typer) — CLI 框架
- [Rich](https://github.com/Textualize/rich) — 终端格式化
- [Pydantic](https://github.com/pydantic/pydantic) — 数据验证

## 许可证

MIT
