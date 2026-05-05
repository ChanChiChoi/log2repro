# 更新日志

## [未发布]

### D8 — 问题原因分析与修复推荐

- 新增 `--analyze` CLI 参数，开启根因分析模式
- 新增 `SYSTEM_PROMPT_ANALYSIS` 分析专用系统提示
- 新增 `generators/analysis.py` 中的 `generate_analysis()` 函数
- `AnalysisResult` 和 `FixRecommendation` 数据模型（`models.py`）
- `analysis.md` 输出：根因、影响、修复推荐
- 修复建议按置信度排序（HIGH / MEDIUM / LOW）
- Python API `analyze(traceback)` 支持编程调用
- 使用 `--analyze` 时与复现文件同时输出 `analysis.md`
- 31 个单元测试覆盖解析、生成、CLI 集成

### D7 — 文档与打磨

- 在 `docs/` 下添加完整文档（9 个文件）
- 生成 `CODE_LOGIC.md`，逐模块记录代码逻辑
- 添加 GitHub `README.md`
- 添加 `--extra-body` CLI 参数，支持 LLM API 额外参数
- 思考模型支持：`content` 为 None 时回退使用 `reasoning_content`
- 思考内容随 `--verbose` 自动打印
- CLI 自动检测：Sentry JSON / CI 日志 / Stacktrace 格式路由
- 扩展 ANSI 转义码剥离（CSI、OSC、private mode）
- Sentry 解析器：从 frame `vars` 字典提取 `context_vars`
- 新增 `error_reproduced_rate` 评估指标
- PyPI 打包 + GitHub Actions 工作流

### D6 — 基准测试框架

- `benchmarks/prompt_variants.py` — 5 个 prompt 变体（P1-P5）
- `benchmarks/runner.py` — 基准测试执行引擎
- `benchmarks/validator.py` — 幻觉 + 触发检测
- `benchmarks/report.py` — Markdown 报告生成
- `benchmarks/mock_responses.py` — 确定性 mock 响应

### D5 — 高级解析器

- `parsers/sentry.py` — Sentry JSON 解析器（完整实现）
- `parsers/ci_log.py` — CI 日志解析器，支持 ANSI 剥离
- CLI 多格式自动检测

### D4 — 质量评估

- `eval_metrics.py` — 4 个质量指标
  - 代码可运行率
  - 依赖冲突率
  - Mock 覆盖率
  - Token 效率
- `GenerationInput`、`SingleEvalResult`、`BatchEvalResult` 数据模型
- `BatchEvalResult.report()` — Markdown 表格输出

### D3 — 沙箱执行与自动修复

- `validators/sandbox.py` — 完整沙箱实现
  - `venv` 创建 + pip 安装
  - `subprocess.run()` 带超时
  - 通过环境变量隔离网络
  - `SandboxResult` 数据类
- `validators/auto_fix.py` — 自动修复链
  - 错误分类（7 种可修复类型）
  - 定向 LLM 修复提示
  - 3 轮修复循环 + 优雅降级
  - `FixResult` 数据类
- CLI 集成：`--sandbox-timeout`、`--max-refine`、`--output-dir`、`--verbose`
- `_generate_readme()` — 生成 README_repro.md（含修复历史和建议）

### D2 — LLM 生成与沙箱反馈

- `generators/code_gen.py` — LLM 生成流水线
  - `_call_llm()` — 隔离的 litellm 入口点
  - `generate_repro_script()` — 含沙箱反馈的完整流水线
  - `parse_llm_response()` — Markdown 代码块提取
  - 指数退避重试
- `generators/prompts.py` — 系统提示 + Jinja2 模板
  - 3 个系统提示（通用/网络/数据库）
  - `select_system_prompt()` — 按错误类型自动选择
  - `REFINE_PROMPT_TEMPLATE` — 沙箱反馈修正
- 沙箱反馈循环：生成 → 验证 → 修正（最多 N 轮）

### D1 — 核心解析与 AST 提取

- `parsers/base.py` — `ParsedTrace` 模型、`BaseParser` 抽象类
- `parsers/stacktrace.py` — Python traceback 解析器
  - 基于正则的解析（`re.MULTILINE`）
  - 链式异常支持
  - 上下文变量提取
- `extractors/ast_parser.py` — AST 上下文提取
  - 函数签名提取（含类型 + 默认值）
  - Import 语句提取
  - 变量注解提取
- `cli.py` — Typer CLI 入口
  - `log2repro run` 命令
  - `log2repro version` 命令
  - 仅解析模式（dry-run）
- `utils/io.py` — 输入读取（文件/stdin/原始文本）

## 版本历史

| 版本 | 里程碑 | 测试数 |
|------|--------|--------|
| 0.1.0 | D1-D6 核心解析+AST+LLM+沙箱+评估+解析器+基准测试 | ~385 |
| 0.2.0 | D7 文档 + PyPI 打包 | ~385 |
| 0.2.1 | D7 --extra-body、思考模型支持、CLI 自动检测 | ~385 |
| 0.3.0 | D8 根因分析 + 修复推荐 | ~416 |
