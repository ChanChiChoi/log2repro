# Evaluation Guide

## Overview

log2repro includes 4 quality metrics to evaluate generated reproduction scripts. These metrics measure correctness, dependency hygiene, mock quality, and token efficiency.

## Metrics

### 1. Code Runnable Rate (代码可运行率) ↑

**Question:** Does the generated script execute without infrastructure errors?

**Method:** `check_runnable(files, timeout)`

- Writes files to a temp directory
- Runs `reproduce.py` in a subprocess
- Classifies the result:

| Exit Code | stderr Contains | Verdict |
|-----------|----------------|---------|
| 0 | — | Runnable (success) |
| Non-zero | `ModuleNotFoundError` / `ImportError` / `SyntaxError` / `NameError` / `AttributeError` | **Not runnable** |
| Non-zero | Other exception | Runnable (app-level error is expected) |
| Timeout | — | Runnable (timeout ≠ code error) |

**Interpretation:** A high runnable rate means the LLM generates syntactically valid, importable code. App-level errors (like the target `ValueError`) are expected and count as runnable.

### 2. Dependency Conflict Rate (依赖冲突率) ↓

**Question:** Does `requirements.txt` have version conflicts?

**Method:** `check_dep_conflict(requirements_text)`

- Parses each line with pip's requirement syntax
- Detects:
  - Unparseable lines
  - Same package with conflicting version constraints

**Example conflicts:**
```
requests>=2.28
requests<2.25    # Conflict!
```

**Interpretation:** A low conflict rate means the LLM generates clean dependency specs. Zero is ideal.

### 3. Mock Coverage Rate (Mock 覆盖率) ↑

**Question:** Are external calls (network, DB) properly mocked?

**Method:** `check_mock_coverage(repro_code)`

- Scans for real external calls:

```python
_REAL_CALL_PATTERNS = [
    "requests.get(", "requests.post(", "requests.put(",
    "requests.delete(", "requests.patch(",
    "httpx.get(", "httpx.post(",
    "aiohttp.ClientSession(",
    "sqlite3.connect(", "psycopg2.connect(",
    "sqlalchemy.create_engine(",
    "open(",  # file I/O
]
```

- Checks if each call is inside a `with patch(...)` block
- Calculates: `coverage = 1 - (unmocked / total)`

**Detection logic:**
1. Find all real call occurrences
2. For each call, scan upward for a `with patch(...)` block
3. Check indentation to confirm the call is inside the block

**Interpretation:** 1.0 = all external calls are mocked. 0.0 = no mocking at all.

### 4. Token Efficiency (Token 效率) ↑

**Question:** How many errors are reproduced per 1,000 tokens?

**Method:** Calculated from `tokens_used` and `error_reproduced` flag.

```
token_efficiency = errors_reproduced / (tokens_used / 1000)
```

**Interpretation:** Higher is better. A value of 1.0 means 1 error reproduced per 1,000 tokens.

### 5. Error Reproduced Rate (错误复现率) ↑

**Question:** Does the sandbox reproduce the original error?

**Method:** Calculated from `error_reproduced` flag across all scripts.

```
error_reproduced_rate = scripts_with_error_reproduced / total_scripts
```

**Interpretation:** The primary effectiveness metric. 1.0 means every generated script triggers the original error.

## Using the Evaluation API

### Single Evaluation

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
print(f"Runnable: {result.runnable}")
print(f"Dep conflict: {result.dep_conflict}")
print(f"Mock coverage: {result.mock_coverage}")
print(f"Error reproduced: {result.error_reproduced}")
```

### Batch Evaluation

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

### Report Output

`batch.report()` generates a Markdown table:

```markdown
## Evaluation Report

| Metric | Value |
|--------|-------|
| 代码可运行率 | 0.85 |
| 依赖冲突率 | 0.05 |
| Mock 覆盖率 | 0.92 |
| Token 效率 | 0.75 |

### Issues

| Trace | Issue |
|-------|-------|
| trace_3 | Script not runnable: ModuleNotFoundError: No module named 'pandas' |
| trace_5 | Unmocked call: requests.get( at line 12 |
```

## Benchmark Framework

### Running Benchmarks

```bash
# Full benchmark (5 variants × 5 traces × N runs)
uv run python -m benchmarks.runner

# Quick test
uv run python -m benchmarks.runner --num-runs 1
```

### Prompt Variants

| Variant | Description | Expected Trade-off |
|---------|-------------|-------------------|
| P1_SPEED | Minimal, 30-line limit | Fast but may miss edge cases |
| P2_MINIMAL | 3 rules, no examples | Balanced speed/quality |
| P3_BALANCED | Default production prompt | Best overall |
| P4_COMPLETE | Few-shot examples | Highest quality, most tokens |
| P5_SECURITY | Audit mode, no eval/exec | Safest, may be overly restrictive |

### Benchmark Output

The benchmark generates:
- Per-variant metrics (trigger rate, hallucination rate, avg tokens, file completeness)
- Per-trace breakdown
- Markdown comparison table

### Validation Metrics

The benchmark validator checks:

| Check | Description |
|-------|-------------|
| `triggers_error` | Code contains the original exception type or `raise` |
| `hallucinated` | References unknown libraries (not in stdlib + known packages) |
| `all_files_present` | All 3 required files are generated |

## Improving Scores

### Low Runnable Rate

- Check if LLM generates valid Python syntax
- Verify `requirements.txt` lists all needed packages
- Increase `--max-refine` for more sandbox fix rounds

### High Dependency Conflict Rate

- Review LLM output for duplicate package entries
- Use `--model gpt-4o` for better instruction following

### Low Mock Coverage Rate

- Use network/database-specific system prompts
- Add explicit mock instructions in prompt variants
- Check if the error type triggers the right system prompt

### Low Token Efficiency

- Use shorter prompts (P1_SPEED or P2_MINIMAL)
- Reduce `--max-refine` rounds
- Use cheaper/faster models for non-critical traces
