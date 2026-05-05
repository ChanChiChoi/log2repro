# 贡献指南

## 开发环境搭建

```bash
# 克隆
git clone https://github.com/ChanChiChoi/log2repro.git
cd log2repro

# 安装开发依赖
uv sync --group dev

# 验证环境
uv run pytest --co -q  # 列出测试但不运行
```

## 项目结构

```
src/log2repro/          # 主包
├── cli.py              # CLI 入口
├── eval_metrics.py     # 质量指标
├── parsers/            # 日志解析
├── extractors/         # AST 提取
├── generators/         # LLM 生成
├── validators/         # 沙箱 + 自动修复
└── utils/              # I/O 工具

tests/                  # 测试套件
├── fixtures/           # 30+ 错误 trace 样本
└── test_*.py           # 测试模块

benchmarks/             # 基准测试框架
```

## 运行测试

```bash
# 全部测试（385 个测试，约 2.5 分钟）
uv run pytest -v

# 特定模块
uv run pytest tests/test_sandbox.py -v

# 带覆盖率
uv run pytest --cov=log2repro --cov-report=term-missing

# 遇到第一个失败即停止
uv run pytest -x
```

## 代码风格

- **格式化/检查工具：** Ruff
- **行宽：** 88 字符（兼容 Black）
- **类型提示：** 公共函数必须有
- **文档字符串：** 公共 API 使用 Google 风格

```bash
# 检查
uv run ruff check src/ tests/

# 格式化
uv run ruff format src/ tests/
```

## 添加新解析器

1. 创建 `src/log2repro/parsers/my_parser.py`
2. 实现 `BaseParser` 接口：

```python
from log2repro.parsers.base import BaseParser, ParsedTrace

class MyParser(BaseParser):
    def can_parse(self, text: str) -> bool:
        # 返回 True 表示此解析器能处理该输入
        ...

    def parse(self, text: str) -> list[ParsedTrace]:
        # 解析文本并返回 traces
        ...
```

3. 在 `tests/test_my_parser.py` 中添加测试
4. 在 `tests/fixtures/` 中添加 trace 夹具
5. 在 `cli.py` 解析器链中注册

## 添加新指标

1. 在 `src/log2repro/eval_metrics.py` 中添加函数
2. 集成到 `evaluate_single()` 中
3. 在 `tests/test_eval_metrics.py` 中添加测试
4. 如有需要更新 `BatchEvalResult.report()`

## 修改提示

1. 编辑 `src/log2repro/generators/prompts.py`
2. 运行基准测试进行对比：

```bash
uv run python -m benchmarks.runner
```

3. 更新 `CODE_LOGIC.md` 第 6.1 节

## 测试夹具

将真实错误 trace 添加到 `tests/fixtures/`：

```
tests/fixtures/
├── connection_error.txt
├── sqlalchemy_not_found.txt
├── chained_exception.txt
├── sentry_payload.json
└── ci_log_ansi.txt
```

每个夹具应是最小的、自包含的错误 trace。

## Mock LLM 调用

所有 LLM 调用通过 `code_gen.py` 中的 `_call_llm()`。在测试中 mock 它：

```python
from unittest.mock import patch

def test_my_feature():
    mock_response = "```python\nprint('hello')\n```"
    with patch("log2repro.generators.code_gen._call_llm", return_value=mock_response):
        # 你的测试代码
        ...
```

## 沙箱测试

沙箱测试在 venv 中运行真实的 Python 脚本。速度较慢但测试实际行为：

```python
def test_sandbox_execution():
    result = run_in_sandbox(
        script_path=Path("test_script.py"),
        timeout=10,
        expected_error="ValueError: test",
    )
    assert result.error_reproduced
```

## Pull Request 流程

1. 从 `main` 创建功能分支
2. 编写代码 + 测试
3. 运行完整测试套件：`uv run pytest -v`
4. 运行检查工具：`uv run ruff check src/ tests/`
5. 如果修改了模块逻辑，更新 `CODE_LOGIC.md`
6. 提交 PR 并附上清晰的描述

## 提交信息

遵循约定式提交：

```
feat: 添加 Sentry JSON 解析器
fix: 处理下划线前缀的异常类型
docs: 更新沙箱变更的 CODE_LOGIC.md
test: 添加链式异常的边界测试
refactor: 提取 _call_llm 以提高可测试性
```

## 文档

修改代码时，根据需要更新以下文档：

| 变更 | 需要更新 |
|------|----------|
| 新模块 | `CODE_LOGIC.md` + `docs/architecture.md` |
| 新 CLI 参数 | `docs/user-guide.md` + `CODE_LOGIC.md` §9 |
| 新指标 | `docs/evaluation.md` + `CODE_LOGIC.md` §8 |
| 新解析器 | `docs/parser-reference.md` + `CODE_LOGIC.md` §4 |
| 提示变更 | `docs/llm-prompt-design.md` + `CODE_LOGIC.md` §6 |
