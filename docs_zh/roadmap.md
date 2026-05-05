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

### D8 — 问题原因分析与修复推荐 ✅

- [x] `--analyze` CLI 参数，开启问题原因分析模式
- [x] LLM 提示词设计，输出结构化分析（原因 → 影响 → 修复方案）
- [x] `analysis.md` 输出：根因、受影响代码路径、修复推荐
- [x] 修复建议按置信度排序（高/中/低）
- [x] 与复现流程集成：一次流水线同时输出分析 + 复现
- [x] Python API `analyze(traceback)` 支持编程调用
- [x] 分析输出结构与内容质量的单元测试

### D9 — Python 错误格式完整性（规划中）

> 详细参考：[python-error-format-gaps.md](python-error-format-gaps.md)

- [ ] SyntaxError / IndentationError / TabError 带 `^` 指针格式
  - 独立 SyntaxError：返回 0 traces（无 call site 匹配）
  - 有前序调用栈的 SyntaxError：指向错误的 frame（最后一个 `in func` 的 frame，而非 SyntaxError 行）
  - 支持 `File "x.py", line N` 格式（无 `, in func_name`）
  - 从指针位置提取错误列号
- [ ] ExceptionGroup / BaseExceptionGroup（Python 3.11+）
  - `+ Exception Group Traceback` 标题不被 `^Traceback` 正则匹配
  - `|` 前缀阻止子异常中 `_RE_CALL_SITE` 匹配
  - 递归解析子异常，将所有子 trace 提取为独立 ParsedTrace 对象
- [ ] Logging exc_info 前缀格式（高优先级）
  - `2024-01-15 ERROR ... Traceback (most recent call last):` — 时间戳前缀导致 `^Traceback` 不匹配
  - 生产日志中最常见的格式（`logging.exception()`、`logging.error(exc_info=True)`）
- [ ] Warning 格式（`file:line: WarningType: message`）
  - 新增 `WarningParser` 处理非 traceback 的 warning 输出
- [ ] RecursionError 深度保留
  - 解析 `[Previous line repeated N more times]` 行
  - 在 ParsedTrace 元数据中存储重复次数
- [ ] Exception notes（Python 3.11+ `add_note()`）
  - 捕获异常行之后的 note 行
  - 给 `ParsedTrace` 新增 `notes: list[str]` 字段
- [ ] Re-raise 标注（无参数 `raise`）
  - 裸 `raise` 当前被当作普通 traceback 解析
  - 应标注为 re-raise 以提供更好的复现上下文
- [ ] 更新 `_RE_CALL_SITE` 可选匹配无 `in func` 的 `File "x.py", line N`

### D10 — LLM / Agent / MCP 错误格式支持（规划中）

> 详细参考：[python-error-format-gaps.md § LLM/Agent/MCP](python-error-format-gaps.md#10-llm-api-error-json-response)

- [ ] LLM API Error JSON 解析器（`APIErrorParser`）
  - 解析 OpenAI / Anthropic / LiteLLM JSON 错误响应
  - 提取 `error.type`、`error.code`、`error.message` → `ParsedTrace`
- [ ] Token / Context Window 错误解析器（`LLMErrorParser`）
  - 解析纯文本的上下文限制和速率限制消息
  - 提取模型名、token 数量、重试时间
- [ ] MCP JSON-RPC 错误解析器（`MCPRpcParser`）
  - 解析 MCP stderr 中的 `{"jsonrpc":"2.0","error":{"code":...,"message":...}}`
  - 将 JSON-RPC 错误码映射为可读类型
- [ ] LangChain Agent verbose 输出解析器（`AgentLogParser`）
  - 解析 `Thought/Action/Observation` 链式格式
  - 从 `Observation` 行提取工具名、参数、错误
- [ ] Agent tool 执行错误（截断格式）
  - 处理 `[AgentError] Tool execution failed:` 风格输出
- [ ] Google Gemini API 错误解析器（`GeminiErrorParser`）
  - 解析 `google.api_core.exceptions`（BadRequest, ResourceExhausted, PermissionDenied）
  - 处理 `google-genai` SDK 的 `ClientError`/`ServerError` 格式
- [ ] A2A 协议错误解析器（`A2AErrorParser`）
  - 解析 Agent-to-Agent JSON-RPC 2.0 错误
  - 映射 A2A 专属错误码：-32001 Task not found、-32002 Task cannot be canceled、-32003 Push notification not supported、-32004 Unsupported operation、-32005 Content type not supported
- [ ] 内容审核/安全过滤错误
  - 解析 `content_policy_violation`（OpenAI）、安全相关的 `invalid_request_error`（Anthropic）
  - 提取违规类别用于复现上下文
- [ ] Tool Calling / Function Calling 错误
  - 解析 JSON Schema 验证失败（`strict: true` 不支持的字段：`format`、`allOf`、`anyOf`）
  - 解析工具参数类型不匹配错误
  - 解析 `run_requires_action` / 工具输出格式错误（OpenAI Assistants API）
- [ ] OpenAI Responses API 错误
  - 解析 `response.failed` SSE 事件：`{"type":"response.failed","response":{"error":{...}}}`
  - 与 Chat Completions 格式并存处理
- [ ] Agent 框架错误（CrewAI / AutoGen / Google ADK / Semantic Kernel）
  - 解析 CrewAI `CrewError` / `AgentExecutionError` 包装格式
  - 解析 AutoGen `TerminationException` / `GroupChatError` 格式
  - 解析 Google ADK `google.adk.errors` 格式
- [ ] LiteLLM 统一异常体系
  - 解析 8 个异常类：`AuthenticationError`、`RateLimitError`、`ContextWindowExceededError`、`BudgetExceededError`、`ContentPolicyViolationError` 等
  - 映射 LiteLLM proxy 统一 JSON 错误格式
- [ ] Anthropic Extended Thinking 错误
  - 解析 thinking block 格式错误和 `budget_tokens` 超限错误
- [ ] Embedding API 错误
  - 解析 OpenAI/Anthropic embedding 端点错误（维度不匹配、输入过长）
  - 扩展 `APIErrorParser` 处理 embedding 专属错误码
- [ ] Batch API 错误
  - 解析 OpenAI Batch API `batch.failed` 状态（含错误行数统计）
  - 扩展 `APIErrorParser` 处理 batch 专属错误格式
- [ ] Realtime API WebSocket 错误
  - 解析 OpenAI Realtime API WebSocket 错误事件
  - 处理连接级和会话级错误类型
- [ ] 音频 API 错误（Whisper / TTS / Realtime Voice）
  - 解析 OpenAI Whisper 语音转写错误（不支持的编码、文件大小、时长限制）
  - 解析 TTS 错误（无效 voice/model、输入文本过长）
  - 解析 Realtime Voice API 音频流错误
- [ ] 文档/PDF 输入错误
  - 解析 Anthropic PDF 错误（`document` content block、base64 编码、大小 ~10MB 限制）
  - 解析 Google Gemini 文件上传错误（`client.files.upload()`、MIME type）
  - 解析 OpenAI Assistants API 文件上传错误
- [ ] Google Gemini 多模态错误
  - 解析视频上传/处理错误（格式、大小、时长）
  - 解析音频输入错误
  - 解析 File API 错误（`client.files.upload()`）
  - 处理多模态 token 计算差异
- [ ] 图片生成 API 错误（DALL-E / Imagen）
  - 解析生成特有的内容策略违规
  - 解析无效生成参数（size、quality、style、prompt 长度）
  - 解析生成端点专属速率限制
- [ ] 视频理解错误
  - 解析 Gemini 视频上传/处理错误
  - 解析视频时长和格式限制
- [ ] 多模态 token 计算错误
  - 解析基于分辨率的图片 token 错误（OpenAI）
  - 解析按媒体类型的 token 成本错误（Gemini）
  - 解析混合媒体上下文窗口计算错误
- [ ] LLM 专用系统提示
  - 新增 `SYSTEM_PROMPT_LLM`，针对 LLM/Agent 错误（mock API 响应、重试逻辑）
  - 错误类型匹配 `openai.*`、`anthropic.*`、`litellm.*`、`langchain.*`、`google.*`、`crewai.*` 时自动选择

### D11 — 语言扩展（规划中）

- [ ] JavaScript/TypeScript 堆栈跟踪解析器
- [ ] Java 堆栈跟踪解析器
- [ ] Go panic 解析器
- [ ] Rust panic 解析器
- [ ] 语言专用系统提示

### D12 — Web UI（规划中）

- [ ] FastAPI 后端
- [ ] React 前端
- [ ] 粘贴即复现的 Web 界面
- [ ] 历史记录 / 已保存的复现
- [ ] 可分享的复现链接

### D13 — CI/CD 集成（规划中）

- [ ] GitHub Action
- [ ] GitLab CI 模板
- [ ] 在 issue 中自动评论复现脚本
- [ ] Sentry 插件 / webhook

### D14 — 高级功能（规划中）

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
