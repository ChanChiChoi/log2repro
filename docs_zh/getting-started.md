# 快速开始

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

**环境要求：** Python >= 3.10

## 生成第一个复现脚本

### 1. 准备错误日志

创建 `error.log`，内容为一段 Python traceback：

```
Traceback (most recent call last):
  File "/app/api/handler.py", line 42, in fetch_user
    user = db.query(User).filter_by(id=user_id).one()
sqlalchemy.exc.NoResultFound: No row was found for one()
```

### 2. 运行 log2repro

```bash
log2repro run error.log --output-dir ./repro_out
```

输出：

```
Parsed: sqlalchemy.exc.NoResultFound: No row was found for one() at /app/api/handler.py:42
Generating reproduction script...
Running sandbox verification with auto-fix...
  ✓ reproduce.py
  ✓ requirements.txt
  ✓ mock_data.json
  ✓ README_repro.md
```

### 3. 运行复现脚本

```bash
cd repro_out
pip install -r requirements.txt
python reproduce.py
```

脚本应该会触发原始的 `NoResultFound` 错误。

## 从 stdin 读取

```bash
cat error.log | log2repro run - --output-dir ./repro_out
```

## 直接粘贴文本

```bash
log2repro run 'Traceback (most recent call last):
  File "app.py", line 10, in process
    result = api.fetch(user_id)
requests.exceptions.ConnectionError: Connection refused'
```

## 仅解析模式（dry-run）

只解析日志，不调用 LLM：

```bash
log2repro run error.log --dry-run
```

## 指定模型

```bash
log2repro run error.log --model gpt-4o --output-dir ./repro_out
log2repro run error.log --model claude-3-opus --output-dir ./repro_out
log2repro run error.log --model ollama/llama3 --output-dir ./repro_out
```

log2repro 使用 [litellm](https://github.com/BerriAI/litellm)，支持所有 litellm 兼容的模型。

## 配置

### LLM API 密钥

设置对应提供商的环境变量：

```bash
# OpenAI
export OPENAI_API_KEY="sk-..."

# Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# 或使用 .env 文件
```

### 沙箱超时

```bash
log2repro run error.log --sandbox-timeout 20
```

### 修正轮次

```bash
log2repro run error.log --max-refine 3
```

## 常见问题

**Q: 生成的脚本没有复现错误？**

尝试增加 `--max-refine`，或查看 `README_repro.md` 中的修复建议。

**Q: 能否用于非 Python 错误？**

目前仅完全支持 Python traceback。Sentry JSON 和 CI 日志部分支持。详见 [解析器参考](parser-reference.md)。

**Q: 我的代码会被发送到 LLM 吗？**

会。traceback、函数签名、import 语句和变量名会发送给 LLM，但**不会**发送源文件完整内容。使用 `--dry-run` 可以预览将发送的内容。

**Q: 费用是多少？**

单次生成约消耗 2,000-4,000 tokens。包含沙箱修正约 6,000-10,000 tokens。
