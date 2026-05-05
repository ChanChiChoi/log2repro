# 评估指南

## 概述

log2repro 包含 4 个质量指标，用于评估生成的复现脚本。这些指标衡量正确性、依赖卫生、mock 质量和 token 效率。

## 指标

### 1. 代码可运行率 ↑

**问题：** 生成的脚本能否在没有基础设施错误的情况下执行？

**方法：** `check_runnable(files, timeout)`

- 将文件写入临时目录
- 在子进程中运行 `reproduce.py`
- 分类结果：

| 退出码 | stderr 包含 | 判定 |
|--------|-------------|------|
| 0 | — | 可运行（成功） |
| 非零 | `ModuleNotFoundError` / `ImportError` / `SyntaxError` / `NameError` / `AttributeError` | **不可运行** |
| 非零 | 其他异常 | 可运行（应用级错误是预期的） |
| 超时 | — | 可运行（超时 ≠ 代码错误） |

**解读：** 高可运行率意味着 LLM 生成了语法正确、可导入的代码。应用级错误（如目标 `ValueError`）是预期的，计为可运行。

### 2. 依赖冲突率 ↓

**问题：** `requirements.txt` 是否有版本冲突？

**方法：** `check_dep_conflict(requirements_text)`

- 用 pip 的需求语法解析每一行
- 检测：
  - 无法解析的行
  - 同一包的不同版本约束冲突

**冲突示例：**
```
requests>=2.28
requests<2.25    # 冲突！
```

**解读：** 低冲突率意味着 LLM 生成了干净的依赖规范。零是理想值。

### 3. Mock 覆盖率 ↑

**问题：** 外部调用（网络、数据库）是否被正确 mock？

**方法：** `check_mock_coverage(repro_code)`

- 扫描真实的外部调用：

```python
_REAL_CALL_PATTERNS = [
    "requests.get(", "requests.post(", "requests.put(",
    "requests.delete(", "requests.patch(",
    "httpx.get(", "httpx.post(",
    "aiohttp.ClientSession(",
    "sqlite3.connect(", "psycopg2.connect(",
    "sqlalchemy.create_engine(",
    "open(",  # 文件 I/O
]
```

- 检查每个调用是否在 `with patch(...)` 块内
- 计算：`覆盖率 = 1 - (未 mock 数 / 总数)`

**检测逻辑：**
1. 找到所有真实调用出现位置
2. 对每个调用，向上扫描 `with patch(...)` 块
3. 检查缩进确认调用在块内

**解读：** 1.0 = 所有外部调用都被 mock。0.0 = 完全没有 mock。

### 4. Token 效率 ↑

**问题：** 每 1,000 token 能复现多少个错误？

**方法：** 根据 `tokens_used` 和 `error_reproduced` 标志计算。

```
token_efficiency = 复现的错误数 / (token 用量 / 1000)
```

**解读：** 越高越好。值为 1.0 表示每 1,000 token 复现 1 个错误。

### 5. 错误复现率 ↑

**问题：** 沙箱是否复现了原始错误？

**方法：** 根据所有脚本的 `error_reproduced` 标志计算。

```
error_reproduced_rate = 复现成功的脚本数 / 总脚本数
```

**解读：** 核心效果指标。1.0 表示每个生成的脚本都能触发原始错误。

## 使用评估 API

### 单次评估

```python
from log2repro.eval_metrics import evaluate_single, GenerationInput

gen = GenerationInput(
    trace_name="connection_error",
    files={
        "reproduce.py": "...",
        "requirements.txt": "requests==2.28.0",
        "mock_data.json": "{}",
    },
    tokens_used=1200,
    expected_error="ConnectionError: Connection refused",
)

result = evaluate_single(gen, sandbox_timeout=10)
print(f"可运行: {result.runnable}")
print(f"依赖冲突: {result.dep_conflict}")
print(f"Mock 覆盖率: {result.mock_coverage}")
print(f"错误复现: {result.error_reproduced}")
```

### 批量评估

```python
from log2repro.eval_metrics import evaluate_batch, GenerationInput

inputs = [
    GenerationInput(
        trace_name="trace_1",
        files=files_1,
        tokens_used=800,
        expected_error="ValueError: bad value",
    ),
    GenerationInput(
        trace_name="trace_2",
        files=files_2,
        tokens_used=1200,
        expected_error="ConnectionError: refused",
    ),
]

batch = evaluate_batch(inputs, sandbox_timeout=10)
print(batch.report())
```

### 报告输出

`batch.report()` 生成 Markdown 表格：

```markdown
## 评估报告

| 指标 | 值 |
|------|-----|
| 代码可运行率 | 0.85 |
| 依赖冲突率 | 0.05 |
| Mock 覆盖率 | 0.92 |
| Token 效率 | 0.75 |

### 问题明细

| Trace | 问题 |
|-------|------|
| trace_3 | 脚本不可运行: ModuleNotFoundError: No module named 'pandas' |
| trace_5 | 未 mock 的调用: requests.get( 第 12 行 |
```

## 基准测试框架

### 运行基准测试

```bash
# 完整基准测试（5 个变体 × 5 个 trace × N 次运行）
uv run python -m benchmarks.runner

# 快速测试
uv run python -m benchmarks.runner --num-runs 1
```

### Prompt 变体

| 变体 | 描述 | 预期权衡 |
|------|------|----------|
| P1_SPEED | 最小化，30 行限制 | 快但可能遗漏边界情况 |
| P2_MINIMAL | 3 条规则，无示例 | 速度/质量平衡 |
| P3_BALANCED | 默认生产提示 | 综合最优 |
| P4_COMPLETE | few-shot 示例 | 最高质量，最多 token |
| P5_SECURITY | 审计模式，禁用 eval/exec | 最安全，可能过于严格 |

### 基准测试输出

基准测试生成：
- 每个变体的指标（触发率、幻觉率、平均 token、文件完整率）
- 每个 trace 的明细
- Markdown 对比表格

### 验证指标

基准测试验证器检查：

| 检查项 | 描述 |
|--------|------|
| `triggers_error` | 代码包含原始异常类型或 `raise` |
| `hallucinated` | 引用了未知库（不在标准库 + 已知包中） |
| `all_files_present` | 3 个必需文件全部生成 |

## 提升分数

### 低可运行率

- 检查 LLM 是否生成了有效的 Python 语法
- 验证 `requirements.txt` 列出了所有需要的包
- 增加 `--max-refine` 以获得更多沙箱修复轮次

### 高依赖冲突率

- 检查 LLM 输出中是否有重复的包条目
- 使用 `--model gpt-4o` 以获得更好的指令遵循

### 低 Mock 覆盖率

- 使用网络/数据库专用系统提示
- 在 prompt 变体中添加明确的 mock 指令
- 检查错误类型是否触发了正确的系统提示

### 低 Token 效率

- 使用更短的提示（P1_SPEED 或 P2_MINIMAL）
- 减少 `--max-refine` 轮次
- 对非关键 trace 使用更便宜/更快的模型
