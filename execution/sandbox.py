"""Subprocess helpers used by the agent to run code and tests.

NOTE: this is *not* a security sandbox. Code runs as the current user with the
same filesystem and network access, limited only by a timeout. The only
hardening applied is removing LLM credentials from the child environment.
Run the agent inside a VM or container when working on untrusted code.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

from execution.output_format import format_pytest_output, truncate_lines

# Credentials the agent itself uses; never expose them to code the model writes.
SECRET_ENV_VARS = frozenset({
    "LLM_API_KEY",
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
})


def safe_subprocess_env() -> dict[str, str]:
    """Copy of os.environ without the LLM credentials."""
    return {k: v for k, v in os.environ.items() if k not in SECRET_ENV_VARS}


def run_python_file(
    workspace: Path, filepath: str, timeout: int = 30
) -> str:
    """Run a Python file in the workspace and return combined output."""
    target = workspace / filepath
    if not target.exists():
        return f"Error: {filepath} not found in workspace"

    try:
        result = subprocess.run(
            [sys.executable, filepath],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=safe_subprocess_env(),
        )
    except subprocess.TimeoutExpired:
        return f"Error: execution timed out after {timeout}s"

    output = result.stdout + result.stderr
    if result.returncode != 0:
        output += f"\n* EXIT CODE: {result.returncode}"
    return truncate_lines(output or "(no output)", max_lines=30)


def run_pytest(workspace: Path, test_path: str = ".", timeout: int = 60) -> str:
    """Run pytest in the workspace and return formatted output with pass/fail summary."""
    args = [sys.executable, "-m", "pytest", test_path, "-v", "--tb=short"]
    try:
        result = subprocess.run(
            args,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=safe_subprocess_env(),
        )
    except subprocess.TimeoutExpired:
        # Timeout escalation — retry with doubled timeout
        try:
            result = subprocess.run(
                args, cwd=workspace, capture_output=True, text=True, timeout=timeout * 2,
                env=safe_subprocess_env(),
            )
        except subprocess.TimeoutExpired:
            return f"[TEST_RESULT:ERROR] passed=0 failed=0 errors=0\nError: pytest timed out after {timeout * 2}s"

    raw = result.stdout + result.stderr
    output = format_pytest_output(raw)

    passed, failed, errors = parse_pytest_counts(raw)

    status = "PASS" if result.returncode == 0 else "FAIL"
    prefix = f"[TEST_RESULT:{status}] passed={passed} failed={failed} errors={errors}\n"

    return prefix + output


_SUMMARY_COUNT = re.compile(r"(\d+) (passed|failed|errors?)\b")


def parse_pytest_counts(raw: str) -> tuple[int, int, int]:
    """Return (passed, failed, errors) from pytest's final summary line.

    Pytest prints e.g. ``=== 5 passed, 1 failed, 2 errors in 0.12s ===``; the
    counts may appear in any order and zero counts are omitted.
    """
    for line in reversed(raw.splitlines()):
        found = _SUMMARY_COUNT.findall(line)
        if found:
            counts = {"passed": 0, "failed": 0, "error": 0}
            for number, kind in found:
                counts["error" if kind.startswith("error") else kind] += int(number)
            return counts["passed"], counts["failed"], counts["error"]
    return 0, 0, 0
