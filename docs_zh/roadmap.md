# 路线图

## 里程碑

### D1 — 核心解析与 AST 提取 ✅

- [x] `ParsedTrace` 模型 + `BaseParser` 抽象类
- [x] Python traceback 正则解析器
- [x] 链式异常支持
- [x] AST 上下文提取（签名、import、变量）
- [x] Typer CLI 入口
- [x] 仅解析模式（dry-run）

### D2 — LLM 生成与沙箱反馈 ✅

- [x] `litellm` 集成（隔离的 `_call_llm()`）
- [x] 3 个系统提示（通用/网络/数据库）
- [x] Jinja2 用户消息模板
- [x] Markdown 代码块解析
- [x] 沙箱反馈循环（生成 → 验证 → 修正）

### D3 — 沙箱执行与自动修复 ✅

- [x] `venv` + `subprocess` 沙箱
- [x] 通过环境变量隔离网络
- [x] 错误分类（7 种可修复类型）
- [x] 自动修复链（3 轮）
- [x] 优雅降级 + 修复建议
- [x] CLI 集成（`--sandbox-timeout`、`--max-refine`、`--output-dir`）
- [x] README_repro.md 生成

### D4 — 质量评估 ✅

- [x] 代码可运行率指标
- [x] 依赖冲突率指标
- [x] Mock 覆盖率指标
- [x] Token 效率指标
- [x] 批量评估 + Markdown 报告

### D5 — 高级解析器 ✅

- [x] Sentry JSON 解析器
- [x] CI 日志解析器（ANSI 剥离）
- [x] CLI 自动检测

### D6 — 基准测试框架 ✅

- [x] 5 个 prompt 变体（P1-P5）
- [x] 基准测试运行器
- [x] 幻觉 + 触发验证
- [x] 每个 trace 的明细
- [x] 确定性 mock 响应

### D7 — 文档与打磨 ✅

- [x] GitHub README.md
- [x] CODE_LOGIC.md（完整代码逻辑文档）
- [x] docs/ 目录（9 个文件）
  - [x] getting-started.md
  - [x] architecture.md
  - [x] user-guide.md
  - [x] parser-reference.md
  - [x] llm-prompt-design.md
  - [x] evaluation.md
  - [x] contributing.md
  - [x] changelog.md
  - [x] roadmap.md

---

### D8 — 语言扩展（规划中）

- [ ] JavaScript/TypeScript 堆栈跟踪解析器
- [ ] Java 堆栈跟踪解析器
- [ ] Go panic 解析器
- [ ] Rust panic 解析器
- [ ] 语言专用系统提示

### D9 — Web UI（规划中）

- [ ] FastAPI 后端
- [ ] React 前端
- [ ] 粘贴即复现的 Web 界面
- [ ] 历史记录 / 已保存的复现
- [ ] 可分享的复现链接

### D10 — CI/CD 集成（规划中）

- [ ] GitHub Action
- [ ] GitLab CI 模板
- [ ] 在 issue 中自动评论复现脚本
- [ ] Sentry 插件 / webhook

### D11 — 高级功能（规划中）

- [ ] 多文件复现（不仅限于单脚本）
- [ ] Docker 沙箱（更强隔离）
- [ ] 自定义 prompt 模板（用户自定义）
- [ ] 复现差异（修复前后对比）
- [ ] 每次生成的费用追踪

---

## 设计原则

1. **LLM 无关** — 不锁定单一提供商
2. **AST 优于幻觉** — 用真实代码提供硬约束
3. **输出前必须沙箱验证** — 交付前先验证
4. **优雅降级** — 始终提供可操作的输出
5. **零侵入** — 粘贴文本即可，无需 SDK
