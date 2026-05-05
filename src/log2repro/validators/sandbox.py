"""Sandbox executor for reproduction scripts.

Runs generated ``reproduce.py`` in an isolated environment:

1. Creates a temporary ``venv``.
2. Installs ``requirements.txt`` into the venv (if provided).
3. Executes the script with network isolation (``no_proxy=*``, empty proxies).
4. Captures stdout / stderr / exit_code with a configurable timeout.
5. Verifies whether the original error was reproduced.

Network isolation is achieved via environment variables rather than OS-level
firewall, keeping the implementation portable and test-friendly.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import venv
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Environment variables injected to block outbound network access.
# These work for ``requests``, ``httpx``, ``urllib``, and most HTTP clients.
_NO_NET_ENV: dict[str, str] = {
    "no_proxy": "*",
    "NO_PROXY": "*",
    "http_proxy": "",
    "HTTP_PROXY": "",
    "https_proxy": "",
    "HTTPS_PROXY": "",
    "all_proxy": "",
    "ALL_PROXY": "",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SandboxResult:
    """Result of a sandbox execution run.

    Attributes:
        stdout: Captured standard output.
        stderr: Captured standard error.
        exit_code: Process exit code.
        timed_out: Whether the execution was killed by timeout.
        error_reproduced: Whether the original error was triggered.
        venv_path: Path to the venv that was created (for debugging).
        pip_ok: Whether ``pip install`` succeeded (``True`` if skipped).
    """

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False
    error_reproduced: bool = False
    venv_path: str = ""
    pip_ok: bool = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_exc_type(expected_error: str) -> str:
    """Extract the exception type name from an error string.

    Examples:
        >>> _extract_exc_type("ValueError: bad value")
        'ValueError'
        >>> _extract_exc_type("requests.exceptions.SSLError: cert expired")
        'SSLError'
        >>> _extract_exc_type("KeyError")
        'KeyError'
    """
    colon_idx = expected_error.find(":")
    if colon_idx == -1:
        type_str = expected_error.strip()
    else:
        type_str = expected_error[:colon_idx].strip()

    if "." in type_str:
        type_str = type_str.rsplit(".", 1)[-1]

    return type_str


def _check_error_reproduced(stderr: str, expected_error: str) -> bool:
    """Check whether the sandbox stderr reproduces the expected error.

    Extracts the exception type from *expected_error* and searches for it
    in *stderr* (which typically contains a Python traceback).
    """
    if not expected_error:
        return False

    exc_type = _extract_exc_type(expected_error)
    if not exc_type:
        return False

    return exc_type in stderr


def _create_venv(venv_dir: Path) -> Path:
    """Create a lightweight virtual environment.

    Returns the path to the venv ``bin/`` (or ``Scripts/`` on Windows)
    directory.
    """
    logger.info("Creating venv in %s", venv_dir)
    venv.create(venv_dir, with_pip=True, clear=False, symlinks=True)
    bin_dir = venv_dir / ("Scripts" if sys.platform == "win32" else "bin")
    return bin_dir


def _pip_install(
    python: Path,
    requirements: Path,
    *,
    timeout: int = 60,
) -> tuple[bool, str]:
    """Run ``pip install -r requirements.txt`` inside the venv.

    Returns ``(success, error_message)``.
    """
    logger.info("Installing dependencies from %s", requirements)
    try:
        proc = subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(requirements),
             "--quiet", "--no-warn-script-location"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, **_NO_NET_ENV},
        )
        if proc.returncode != 0:
            msg = proc.stderr.strip() or proc.stdout.strip()
            logger.warning("pip install failed (exit %d): %s", proc.returncode, msg[:200])
            return False, msg
        logger.info("pip install succeeded")
        return True, ""
    except subprocess.TimeoutExpired:
        logger.warning("pip install timed out after %ds", timeout)
        return False, f"pip install timed out after {timeout}s"


def _sandbox_env() -> dict[str, str]:
    """Build an environment dict with network isolation."""
    env = os.environ.copy()
    env.update(_NO_NET_ENV)
    return env


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_in_sandbox(
    script_path: str | Path,
    requirements_path: str | Path | None = None,
    timeout: int = 10,
    expected_error: str = "",
) -> SandboxResult:
    """Run a reproduction script in a sandboxed environment.

    1. Creates a temporary venv.
    2. Installs *requirements_path* (if provided).
    3. Runs *script_path* with network isolation and *timeout* seconds limit.
    4. Checks whether *expected_error* appears in stderr.

    Args:
        script_path: Path to ``reproduce.py``.
        requirements_path: Path to ``requirements.txt`` (optional).
        timeout: Maximum execution time in seconds.
        expected_error: Error string to look for in stderr.

    Returns:
        A :class:`SandboxResult` with execution details.
    """
    script_path = Path(script_path)
    if not script_path.exists():
        return SandboxResult(
            stderr=f"Script not found: {script_path}",
            exit_code=1,
            error_reproduced=False,
        )

    logger.info("Running sandbox: %s (timeout=%ds)", script_path, timeout)

    with tempfile.TemporaryDirectory(prefix="log2repro_sandbox_") as tmpdir:
        venv_dir = Path(tmpdir) / "venv"
        bin_dir = _create_venv(venv_dir)
        python = bin_dir / "python"

        # pip install
        pip_ok = True
        pip_err = ""
        if requirements_path is not None:
            req_path = Path(requirements_path)
            if req_path.exists() and req_path.read_text().strip():
                pip_ok, pip_err = _pip_install(python, req_path, timeout=60)

        # Run the script
        try:
            proc = subprocess.run(
                [str(python), str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=script_path.parent,
                env=_sandbox_env(),
            )
            stdout = proc.stdout
            stderr = proc.stderr
            exit_code = proc.returncode
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            stdout = _decode_output(exc.stdout)
            stderr = _decode_output(exc.stderr)
            exit_code = -1
            timed_out = True
            logger.warning("Sandbox timed out after %ds", timeout)

        # Prepend pip error info to stderr if installation failed
        if not pip_ok and pip_err:
            stderr = f"[pip install error]\n{pip_err}\n\n{stderr}"

        reproduced = _check_error_reproduced(stderr, expected_error)

        logger.info(
            "Sandbox result: exit_code=%d, timed_out=%s, reproduced=%s, pip_ok=%s",
            exit_code,
            timed_out,
            reproduced,
            pip_ok,
        )

        return SandboxResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            timed_out=timed_out,
            error_reproduced=reproduced,
            venv_path=str(venv_dir),
            pip_ok=pip_ok,
        )


def _decode_output(data: str | bytes | None) -> str:
    """Safely decode subprocess output."""
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode(errors="replace")
    return data
