"""Auto-fix chain for broken reproduction scripts.

When the sandbox detects a *fixable* infrastructure error (SyntaxError,
ModuleNotFoundError, ImportError, NameError, AttributeError), this module
feeds the error back to the LLM for targeted repair.  After
:data:`MAX_FIX_ROUNDS` unsuccessful attempts it falls back to dry-run mode
and emits human-readable repair suggestions.

Typical usage (called internally by :func:`log2repro.generators.code_gen.generate_repro_script`)::

    from log2repro.validators.auto_fix import auto_fix_loop, FixResult

    result = auto_fix_loop(context, files, sandbox_fn)
    if result.success:
        # result.files contains the fixed reproduction files
    else:
        # result.suggestions contains human-readable repair advice
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable

from log2repro.generators.code_gen import (
    _call_llm,
    parse_llm_response,
)
from log2repro.generators.prompts import select_system_prompt
from log2repro.validators.sandbox import SandboxResult, _extract_exc_type

logger = logging.getLogger(__name__)

MAX_FIX_ROUNDS: int = 3

# Errors that are infrastructure bugs (fixable by editing reproduce.py)
_FIXABLE_ERRORS: frozenset[str] = frozenset({
    "SyntaxError",
    "IndentationError",
    "TabError",
    "ModuleNotFoundError",
    "ImportError",
    "NameError",
    "AttributeError",
    "TypeError",       # often: missing argument, wrong type
    "FileNotFoundError",
})

# Regex to extract a Python traceback line from stderr
_TB_LINE_RE: re.Pattern[str] = re.compile(
    r'^\s*File "(?P<file>[^"]+)",\s*line\s+(?P<line>\d+)',
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class FixResult:
    """Outcome of the auto-fix loop.

    Attributes:
        success: Whether a runnable reproduction was achieved.
        files: The final (possibly fixed) files.
        rounds_used: Number of fix rounds attempted.
        history: Per-round log of ``(error_type, stderr_snippet)``.
        suggestions: Human-readable repair advice (populated on failure).
        degraded: Whether the result is a degraded dry-run fallback.
    """

    success: bool = False
    files: dict[str, str] = field(default_factory=dict)
    rounds_used: int = 0
    history: list[tuple[str, str]] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    degraded: bool = False


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


def _classify_error(stderr: str) -> str | None:
    """Return the fixable error type found in *stderr*, or ``None``.

    Scans the last few lines of the traceback for a known fixable error
    class name.
    """
    for line in reversed(stderr.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("File ") or stripped.startswith("Traceback"):
            continue
        for err_type in _FIXABLE_ERRORS:
            if err_type in stripped:
                return err_type
    return None


def _extract_error_snippet(stderr: str, max_lines: int = 15) -> str:
    """Extract the most relevant part of the traceback (last *max_lines*)."""
    lines = stderr.strip().splitlines()
    return "\n".join(lines[-max_lines:])


def _build_fix_suggestions(
    error_type: str,
    stderr: str,
) -> list[str]:
    """Generate human-readable repair suggestions for a failed fix."""
    suggestions: list[str] = []

    if error_type == "ModuleNotFoundError":
        for line in stderr.splitlines():
            if "No module named" in line:
                module = line.split("No module named")[-1].strip().strip("'\"")
                suggestions.append(
                    f"缺少模块 `{module}`: 请在 requirements.txt 中添加该依赖，"
                    f"或在 reproduce.py 中用 unittest.mock 替代。"
                )
                break
        else:
            suggestions.append("缺少依赖模块，请检查 requirements.txt 是否完整。")

    elif error_type in ("SyntaxError", "IndentationError", "TabError"):
        m = _TB_LINE_RE.search(stderr)
        if m:
            suggestions.append(
                f"语法错误位于第 {m.group('line')} 行，请检查缩进和括号匹配。"
            )
        else:
            suggestions.append("语法错误，请检查 reproduce.py 的缩进和语法。")

    elif error_type == "NameError":
        for line in stderr.splitlines():
            if "is not defined" in line:
                name = line.split("'")[1] if "'" in line else "未知变量"
                suggestions.append(
                    f"变量 `{name}` 未定义，请在脚本中声明或 mock 该对象。"
                )
                break

    elif error_type == "ImportError":
        suggestions.append("导入失败，请确认模块版本兼容性或使用 mock 替代。")

    elif error_type == "AttributeError":
        for line in stderr.splitlines():
            if "has no attribute" in line:
                suggestions.append(f"属性不存在: {line.strip()}")
                break
        else:
            suggestions.append("属性错误，请检查对象类型和可用方法。")

    elif error_type == "TypeError":
        for line in stderr.splitlines():
            if "missing" in line or "unexpected" in line or "argument" in line:
                suggestions.append(f"类型/参数错误: {line.strip()}")
                break
        else:
            suggestions.append("类型错误，请检查函数签名和参数。")

    elif error_type == "FileNotFoundError":
        suggestions.append(
            "文件未找到，请确认 mock_data.json 已正确生成并使用正确路径。"
        )

    else:
        suggestions.append(f"遇到 {error_type}，请手动检查 reproduce.py。")

    return suggestions


# ---------------------------------------------------------------------------
# Refinement prompt (narrowing scope each round)
# ---------------------------------------------------------------------------

_FIX_PROMPT_TEMPLATE: str = """\
自动修复 reproduce.py 中的 {error_type}（第 {round}/{max_rounds} 轮）。

## 沙箱 stderr
```
{stderr}
```

## 当前 reproduce.py
```python
{current_code}
```

## 修复要求
1. 本次只修复 **{error_type}** 相关问题，不要改动其他逻辑
2. 如果是缺少模块，用 unittest.mock 替代或在 requirements.txt 中添加
3. 如果是语法错误，只修正出错行及其上下文
4. 输出完整的修正后文件（```reproduce.py、```requirements.txt、```mock_data.json）
"""


def _build_fix_messages(
    *,
    error_type: str,
    stderr: str,
    current_code: str,
    round_idx: int,
    original_error: str,
) -> list[dict[str, str]]:
    """Build the LLM messages for a targeted fix attempt."""
    from jinja2 import Template

    user_msg = Template(_FIX_PROMPT_TEMPLATE).render(
        error_type=error_type,
        round=round_idx,
        max_rounds=MAX_FIX_ROUNDS,
        stderr=stderr or "(empty)",
        current_code=current_code or "# empty",
    )

    system_prompt = select_system_prompt(original_error)

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Type alias for the sandbox callable
SandboxFn = Callable[[dict[str, str]], SandboxResult]


def auto_fix_loop(
    context_model: str,
    original_error: str,
    initial_files: dict[str, str],
    sandbox_fn: SandboxFn,
    *,
    temperature: float = 0.2,
    max_tokens: int = 2000,
) -> FixResult:
    """Run the auto-fix loop: sandbox → classify → LLM fix → repeat.

    On each iteration:
    1. Calls *sandbox_fn(files)* to get a :class:`SandboxResult`.
    2. If the error is reproduced, returns immediately.
    3. If the error is *fixable*, extracts the error info and calls the LLM
       for a targeted repair.
    4. If the error is *not fixable* or all rounds are exhausted, returns
       a degraded result with human-readable suggestions.

    Args:
        context_model: LLM model identifier.
        original_error: The original error string from the trace.
        initial_files: The first draft of reproduction files.
        sandbox_fn: Callable that takes ``files`` and returns a
            :class:`SandboxResult`.
        temperature: LLM sampling temperature.
        max_tokens: Maximum tokens per LLM call.

    Returns:
        A :class:`FixResult` with the final files or suggestions.
    """
    files = dict(initial_files)
    history: list[tuple[str, str]] = []

    for round_idx in range(1, MAX_FIX_ROUNDS + 1):
        logger.info("Auto-fix round %d/%d", round_idx, MAX_FIX_ROUNDS)

        result = sandbox_fn(files)

        # Success — error reproduced
        if result.error_reproduced:
            logger.info("Round %d: error reproduced successfully", round_idx)
            return FixResult(
                success=True,
                files=files,
                rounds_used=round_idx,
                history=history,
            )

        # pip install failure — not fixable by code edits
        if not result.pip_ok:
            logger.warning("Round %d: pip install failed", round_idx)
            history.append(("pip_install_failed", result.stderr[:500]))
            suggestions = [
                "pip install 失败，请检查 requirements.txt 中的包名和版本约束。",
                f"pip 错误: {result.stderr[:200]}",
            ]
            return FixResult(
                success=False,
                files=files,
                rounds_used=round_idx,
                history=history,
                suggestions=suggestions,
                degraded=True,
            )

        # Classify the error
        error_type = _classify_error(result.stderr)
        if error_type is None:
            # Non-fixable error (e.g. the original app error but wrong one)
            logger.info("Round %d: non-fixable error type, stopping", round_idx)
            snippet = _extract_error_snippet(result.stderr)
            history.append(("non_fixable", snippet))
            return FixResult(
                success=False,
                files=files,
                rounds_used=round_idx,
                history=history,
                suggestions=[f"脚本运行但产生非预期错误，请人工检查: {snippet[:300]}"],
                degraded=True,
            )

        snippet = _extract_error_snippet(result.stderr)
        history.append((error_type, snippet))
        logger.info("Round %d: fixable error detected: %s", round_idx, error_type)

        # Ask LLM for a targeted fix
        messages = _build_fix_messages(
            error_type=error_type,
            stderr=snippet,
            current_code=files.get("reproduce.py", ""),
            round_idx=round_idx,
            original_error=original_error,
        )

        try:
            raw_text = _call_llm(
                model=context_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            new_files = parse_llm_response(raw_text)
            if "reproduce.py" in new_files:
                files = {**files, **new_files}
                logger.info("Round %d: LLM returned updated files", round_idx)
            else:
                logger.warning("Round %d: LLM response missing reproduce.py", round_idx)
        except Exception as exc:
            logger.warning("Round %d: LLM call failed: %s", round_idx, exc)

    # All rounds exhausted — degrade to dry-run
    logger.warning("Auto-fix exhausted after %d rounds", MAX_FIX_ROUNDS)
    suggestions = _build_fix_suggestions(
        history[-1][0] if history else "UnknownError",
        history[-1][1] if history else "",
    )
    return FixResult(
        success=False,
        files=files,
        rounds_used=MAX_FIX_ROUNDS,
        history=history,
        suggestions=suggestions,
        degraded=True,
    )
