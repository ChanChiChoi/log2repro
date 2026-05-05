# LLM Prompt Design

## Overview

log2repro uses a structured prompt strategy to guide LLMs in generating accurate reproduction scripts. The design emphasizes **hard constraints from AST** to prevent hallucination, and **targeted refinement** to fix sandbox failures.

## System Prompts

Three specialized system prompts are selected based on error type:

### SYSTEM_PROMPT_GENERAL

**Default prompt for most Python errors.**

Key constraints:
- Output exactly 3 files: `reproduce.py`, `requirements.txt`, `mock_data.json`
- Use `unittest.mock` for all external calls
- Script must be standalone (≤80 lines)
- Exit with non-zero code on expected error
- No real network, DB, or file system access

### SYSTEM_PROMPT_NETWORK

**For network/IO errors** (`requests.ConnectionError`, `ssl.SSLCertVerificationError`, `httpx.TimeoutException`, etc.)

Additional constraints:
- Mock ALL network calls (`requests.get`, `httpx.AsyncClient`, `urllib.request`, etc.)
- Use `unittest.mock.patch` as context manager
- Never open real sockets

### SYSTEM_PROMPT_DATABASE

**For database errors** (`sqlalchemy.exc.NoResultFound`, `psycopg2.Error`, `sqlite3.OperationalError`, etc.)

Additional constraints:
- Mock ALL database sessions and connections
- Use `MagicMock` for ORM query chains
- Never connect to real databases

### Selection Logic

```python
def select_system_prompt(error: str) -> str:
    if any(kw in error for kw in _NETWORK_KEYWORDS):
        return SYSTEM_PROMPT_NETWORK
    if any(kw in error for kw in _DATABASE_KEYWORDS):
        return SYSTEM_PROMPT_DATABASE
    return SYSTEM_PROMPT_GENERAL
```

**Network keywords:** `requests.`, `httpx.`, `aiohttp.`, `ssl.`, `ConnectionRefused`, `ConnectionError`, `Timeout`, `urllib`, `socket.`, `http.client`

**Database keywords:** `sqlalchemy.`, `psycopg2.`, `sqlite3.`, `pymysql.`, `asyncpg.`, `IntegrityError`, `OperationalError`, `NoResultFound`

## User Message Template

A Jinja2 template injects structured context into the user message:

```jinja2
## Error Information
- **File:** {{ file }}
- **Line:** {{ line }}
- **Error:** {{ error }}

## Call Chain
{% for entry in chain %}- {{ entry }}
{% endfor %}

## Context Variables
{% for var in context_vars %}- {{ var }}
{% endfor %}

{% if signature %}
## Function Signature
```python
{{ signature }}
```
{% endif %}

{% if imports %}
## Imports in Source File
```python
{% for imp in imports %}{{ imp }}
{% endfor %}`
```
{% endif %}

{% if known_vars %}
## Known Variables
{% for name, type_ann in known_vars.items() %}- `{{ name }}`: {{ type_ann }}
{% endfor %}
{% endif %}
```

### Template Variables

| Variable | Source | Purpose |
|----------|--------|---------|
| `file` | `ParsedTrace.file` | Error location |
| `line` | `ParsedTrace.line` | Error location |
| `error` | `ParsedTrace.error` | Error type + message |
| `chain` | `ParsedTrace.chain` | Full call stack |
| `context_vars` | `ParsedTrace.context_vars` | Variable names from traceback |
| `signature` | `ASTContext.signature` | Function signature with types |
| `imports` | `ASTContext.imports` | Import statements from source |
| `known_vars` | `ASTContext.known_vars` | Variables with type annotations |

## AST Context Injection

### Why AST?

Without AST context, LLMs hallucinate:
- Non-existent libraries (e.g., `import pandas` when only `json` is used)
- Wrong function signatures (e.g., missing parameters)
- Incorrect variable names

AST extraction provides **hard constraints** that ground the LLM output in reality.

### What AST Provides

1. **Function signature** — exact parameter names, types, defaults
2. **Import statements** — only real imports from the source file
3. **Annotated variables** — real variable names with type hints

### Example

Given this source code:

```python
from typing import Optional
import requests

USER_API = "https://api.example.com/users"

def fetch_user(user_id: int, timeout: float = 5.0) -> Optional[dict]:
    response = requests.get(f"{USER_API}/{user_id}", timeout=timeout)
    return response.json()
```

AST extracts:
- **Signature:** `def fetch_user(user_id: int, timeout: float = 5.0) -> Optional[dict]`
- **Imports:** `["from typing import Optional", "import requests"]`
- **Known vars:** `{"USER_API": "str"}`

The LLM then generates a script that uses `fetch_user`, `user_id`, `timeout`, and `requests` — not hallucinated alternatives.

## Refinement Prompt

When sandbox verification fails, a refinement prompt is sent to the LLM:

```jinja2
The previously generated reproduce.py did not reproduce the original error.

## Original Error
- **Exception type:** {{ original_error }}
- **File:** {{ file }}:{{ line }}

## Sandbox Execution Result
- **Exit code:** {{ exit_code }}
- **stderr:**
{{ stderr }}

## Current reproduce.py
```python
{{ current_code }}
```

## Requirements
1. Only modify the code causing the issue — do not rewrite the entire script
2. Analyze the new error in stderr and identify the root cause
3. Ensure the modification still reproduces the original exception type `{{ exc_type }}`
4. Output the complete corrected reproduce.py
```

### Refinement Strategy

The refinement is **targeted**, not regenerative:
- Only the problematic code is modified
- The original error type must still be reproduced
- The LLM sees the exact stderr output for diagnosis

## Auto-Fix Prompt

For persistent errors after sandbox refinement, a fix prompt is used:

```jinja2
The reproduce script has a {{ error_type }} that needs fixing.

## Error Details
{{ stderr_snippet }}

## Current reproduce.py
```python
{{ current_code }}
```

## Fix Instructions
{{ fix_instructions }}

Output the complete fixed reproduce.py.
```

### Error-Specific Instructions

| Error Type | Fix Instructions |
|------------|-----------------|
| `SyntaxError` | Check indentation, missing colons, unmatched brackets |
| `ModuleNotFoundError` | Add to requirements.txt or use unittest.mock |
| `ImportError` | Check module exists and version compatibility |
| `NameError` | Ensure variable is defined before use |
| `AttributeError` | Check object type and available methods |
| `TypeError` | Check function signature and argument types |
| `FileNotFoundError` | Use mock_data.json or create temp files |

## Anti-Hallucination Measures

### 1. AST Grounding

Real variable names and imports constrain the LLM to use only what exists in the source code.

### 2. File Validation

`_validate_files()` checks that all 3 required files are present. Missing files trigger a retry with explicit instructions.

### 3. Sandbox Verification

Every generated script runs in a real venv. Import errors and syntax errors are caught before output.

### 4. Auto-Fix Loop

Up to 3 rounds of targeted repair for fixable errors, with graceful degradation to human-readable suggestions.

## Prompt Variants (Benchmarks)

The `benchmarks/prompt_variants.py` module defines 5 variants for comparison:

| Variant | Strategy | Lines Limit | Notes |
|---------|----------|-------------|-------|
| P1_SPEED | Minimal instructions | 30 | Fastest, may miss edge cases |
| P2_MINIMAL | 3 core rules only | 50 | No examples |
| P3_BALANCED | Default prompt | 80 | Production default |
| P4_COMPLETE | With few-shot examples | 100 | Highest quality, most tokens |
| P5_SECURITY | Audit mode | 80 | Explicit security checks |

Run benchmarks to compare:

```bash
uv run python -m benchmarks.runner
```

## Token Usage

Typical token consumption per stage:

| Stage | Tokens (approx) |
|-------|-----------------|
| System prompt | 200-400 |
| User message | 300-600 |
| LLM response | 800-1500 |
| Refinement (per round) | 1000-2000 |
| Auto-fix (per round) | 800-1500 |
| **Total (no fix)** | **~2000-3000** |
| **Total (with fix)** | **~6000-10000** |
