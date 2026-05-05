"""CLI entry point for log2repro.

Usage::

    # Full pipeline: parse → generate → sandbox → auto-fix → output
    log2repro run error.log --output-dir ./repro_out

    # Parse only (no LLM, no sandbox)
    log2repro run error.log --dry-run

    # From stdin
    cat error.log | log2repro run - --output-dir ./repro_out

    # Specify model
    log2repro run error.log --model gpt-4o --output-dir ./repro_out
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from log2repro.extractors.ast_parser import ASTContext, extract_ast_context_from_source
from log2repro.parsers.base import BaseParser
from log2repro.parsers.stacktrace import StacktraceParser
from log2repro.utils.io import read_input, write_output

app = typer.Typer(
    name="log2repro",
    help="Error log → runnable reproduction code generator.",
    add_completion=False,
)
console = Console()
logger = logging.getLogger("log2repro")


def _setup_logging(verbose: bool) -> None:
    """Configure structured logging."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stderr)


def _detect_parser(text: str) -> BaseParser:
    """Auto-detect input format and return the appropriate parser.

    Priority: Sentry JSON > CI Log (ANSI) > Stacktrace (default).
    """
    from log2repro.parsers.ci_log import CILogParser
    from log2repro.parsers.sentry import SentryParser

    sentry = SentryParser()
    if sentry.can_parse(text):
        return sentry
    ci = CILogParser()
    if ci.can_parse(text):
        return ci
    return StacktraceParser()


@app.command()
def run(
    input_source: str = typer.Argument(
        ...,
        help='Input source: file path, "-" for stdin, or raw traceback text.',
    ),
    model: str = typer.Option(
        "gpt-4o",
        "--model",
        "-m",
        help="LLM model to use for code generation.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Parse only; skip LLM generation and sandbox validation.",
    ),
    output_dir: Optional[str] = typer.Option(
        None,
        "--output-dir",
        "-d",
        help="Directory to write output files (reproduce.py, requirements.txt, mock_data.json, README_repro.md).",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Write JSON output to this file instead of stdout (legacy).",
    ),
    sandbox_timeout: int = typer.Option(
        10,
        "--sandbox-timeout",
        help="Maximum seconds for sandbox execution.",
    ),
    max_refine: int = typer.Option(
        2,
        "--max-refine",
        help="Maximum sandbox→LLM refinement rounds.",
    ),
    extra_body: Optional[str] = typer.Option(
        None,
        "--extra-body",
        help='Extra JSON body passed to the LLM API (e.g. \'{"enable_thinking": false}\').',
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging.",
    ),
) -> None:
    """Parse an error log and generate a runnable reproduction script.

    Full pipeline: parse → generate → sandbox → auto-fix → output.
    With ``--dry-run``: parse only, output structured JSON.
    """
    _setup_logging(verbose)

    # Parse --extra-body JSON
    parsed_extra_body: dict[str, object] | None = None
    if extra_body:
        try:
            parsed_extra_body = json.loads(extra_body)
            if not isinstance(parsed_extra_body, dict):
                console.print("[red]Error:[/red] --extra-body must be a JSON object.")
                raise typer.Exit(code=1)
        except json.JSONDecodeError as exc:
            console.print(f"[red]Error:[/red] --extra-body is not valid JSON: {exc}")
            raise typer.Exit(code=1) from exc

    # 1. Read input
    try:
        raw_text = read_input(input_source)
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not raw_text.strip():
        console.print("[red]Error:[/red] Empty input.")
        raise typer.Exit(code=1)

    # 2. Auto-detect format and parse
    parser = _detect_parser(raw_text)
    if not parser.can_parse(raw_text):
        console.print("[yellow]Warning:[/yellow] Input does not match any known format.")

    traces = parser.parse(raw_text)
    if not traces:
        console.print("[red]Error:[/red] Could not extract any trace from the input.")
        raise typer.Exit(code=1)

    # Use the first (most relevant) trace
    trace = traces[0]
    console.print(f"[green]Parsed:[/green] {trace.error} at {trace.file}:{trace.line}")

    # 3. Extract AST context (best-effort)
    ast_context = _try_extract_ast(trace.file, trace.line, trace.chain)

    # --- Dry-run mode: parse only ---
    if dry_run:
        _print_dry_run(trace, ast_context, model, output)
        return

    # --- Full pipeline ---
    _run_full_pipeline(
        trace=trace,
        ast_context=ast_context,
        model=model,
        output_dir=output_dir,
        output=output,
        sandbox_timeout=sandbox_timeout,
        max_refine=max_refine,
        extra_body=parsed_extra_body,
    )


def _print_dry_run(trace, ast_context, model, output) -> None:
    """Output parsed context in dry-run mode."""
    result = {
        "traces": [trace.to_context_dict()],
        "ast_contexts": [ast_context.to_context_dict() if ast_context else {}],
        "model": model,
        "dry_run": True,
    }
    json_str = json.dumps(result, indent=2, ensure_ascii=False)
    if output:
        write_output(json_str, output)
        console.print(f"[green]Output written to[/green] {output}")
    else:
        console.print(Panel(json_str, title="Parsed Context (dry-run)", border_style="green"))


def _run_full_pipeline(
    *,
    trace,
    ast_context,
    model: str,
    output_dir: str | None,
    output: str | None,
    sandbox_timeout: int,
    max_refine: int,
    extra_body: dict[str, object] | None = None,
) -> None:
    """Execute the full generate → sandbox → auto-fix pipeline."""
    from log2repro.generators.code_gen import ReproContext, generate_repro_script
    from log2repro.validators.auto_fix import auto_fix_loop
    from log2repro.validators.sandbox import run_in_sandbox

    # Build context
    ctx = ReproContext(
        trace=trace,
        ast_context=ast_context or ASTContext(),
        model=model,
    )

    # Step 1: Initial generation
    console.print("[blue]Generating[/blue] reproduction script...")
    try:
        files = generate_repro_script(
            ctx,
            sandbox_timeout=sandbox_timeout,
            max_refine_rounds=max_refine,
            extra_body=extra_body,
        )
    except RuntimeError as exc:
        console.print(f"[red]Generation failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    # Step 2: Auto-fix loop (if the built-in refinement didn't fully resolve)
    console.print("[blue]Running[/blue] sandbox verification with auto-fix...")

    def _sandbox_fn(f: dict[str, str]) -> "SandboxResult":
        import tempfile
        with tempfile.TemporaryDirectory(prefix="log2repro_fix_") as td:
            tmp = Path(td)
            for name, content in f.items():
                (tmp / name).write_text(content)
            return run_in_sandbox(
                script_path=tmp / "reproduce.py",
                requirements_path=tmp / "requirements.txt" if "requirements.txt" in f else None,
                timeout=sandbox_timeout,
                expected_error=trace.error,
            )

    fix_result = auto_fix_loop(
        context_model=model,
        original_error=trace.error,
        initial_files=files,
        sandbox_fn=_sandbox_fn,
    )

    final_files = fix_result.files

    # Step 3: Generate README_repro.md
    readme = _generate_readme(trace, fix_result, model)
    final_files["README_repro.md"] = readme

    # Step 4: Write output
    if output_dir:
        _write_to_dir(output_dir, final_files, trace)
    elif output:
        # Legacy JSON output
        result = {
            "traces": [trace.to_context_dict()],
            "files": {k: v for k, v in final_files.items()},
            "fix_success": fix_result.success,
            "fix_rounds": fix_result.rounds_used,
        }
        write_output(json.dumps(result, indent=2, ensure_ascii=False), output)
        console.print(f"[green]Output written to[/green] {output}")
    else:
        _write_to_dir("./repro_out", final_files, trace)


def _write_to_dir(dir_path: str, files: dict[str, str], trace) -> None:
    """Write all output files to a directory."""
    out = Path(dir_path)
    out.mkdir(parents=True, exist_ok=True)

    for name, content in files.items():
        file_path = out / name
        file_path.write_text(content, encoding="utf-8")
        console.print(f"  [green]✓[/green] {file_path}")

    # Summary
    table = Table(title="输出文件", show_header=True)
    table.add_column("文件", style="cyan")
    table.add_column("大小", justify="right")
    table.add_column("说明")
    for name, content in files.items():
        size = f"{len(content)} B"
        desc = {
            "reproduce.py": "复现脚本",
            "requirements.txt": "依赖清单",
            "mock_data.json": "Mock 数据",
            "README_repro.md": "使用说明",
        }.get(name, "")
        table.add_row(name, size, desc)
    console.print(table)
    console.print(f"\n[green]所有文件已输出到[/green] {out.resolve()}")


def _generate_readme(trace, fix_result, model: str) -> str:
    """Generate README_repro.md with usage instructions."""
    status = "✓ 已成功复现原始错误" if fix_result.success else "✗ 未能自动复现（需人工检查）"

    suggestions_section = ""
    if fix_result.suggestions:
        suggestions_section = "\n## 修复建议\n\n"
        for i, s in enumerate(fix_result.suggestions, 1):
            suggestions_section += f"{i}. {s}\n"

    history_section = ""
    if fix_result.history:
        history_section = "\n## 自动修复历史\n\n"
        history_section += "| 轮次 | 错误类型 | 摘要 |\n"
        history_section += "|------|----------|------|\n"
        for i, (err_type, snippet) in enumerate(fix_result.history, 1):
            short = snippet[:80].replace("\n", " ") if snippet else ""
            history_section += f"| {i} | {err_type} | {short} |\n"

    return f"""\
# 复现脚本

## 原始错误

- **文件:** `{trace.file}`
- **行号:** {trace.line}
- **错误:** `{trace.error}`

## 调用链

```
{chr(10).join(trace.chain)}
```

## 复现状态

{status}

- 自动修复轮次: {fix_result.rounds_used}
- 生成模型: {model}

## 使用方法

```bash
# 安装依赖
pip install -r requirements.txt

# 运行复现脚本
python reproduce.py
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `reproduce.py` | 最小复现脚本 |
| `requirements.txt` | Python 依赖 |
| `mock_data.json` | Mock 数据（脚本加载） |
| `README_repro.md` | 本说明文件 |
{history_section}{suggestions_section}
---
*Generated by log2repro at {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}*
"""


@app.command()
def version() -> None:
    """Print the log2repro version."""
    from log2repro import __version__

    console.print(f"log2repro {__version__}")


def _try_extract_ast(
    file_path: str,
    target_line: int,
    chain: list[str],
) -> ASTContext | None:
    """Attempt to extract AST context from the source file.

    Returns ``None`` if the file does not exist or cannot be parsed.
    """
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return None

    target_func: str | None = None
    for entry in chain:
        parts = entry.split(":")
        if len(parts) >= 2 and parts[0] == file_path:
            target_func = parts[1]
            break

    try:
        return extract_ast_context_from_source(
            path.read_text(encoding="utf-8"),
            filename=file_path,
            target_line=target_line,
            target_func=target_func,
        )
    except (SyntaxError, OSError):
        return None


if __name__ == "__main__":
    app()
