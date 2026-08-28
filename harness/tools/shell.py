"""Workspace-scoped shell command tool."""

import subprocess

from typing import Any, Dict

import harness.tools as tools


def run_command(command: str, timeout: int = 120) -> Dict[str, Any]:
    """Run a shell command in the workspace and capture bounded output.

    This is intentionally workspace-scoped, but commands are still arbitrary
    shell commands. The caller should only expose it in trusted workspaces.
    """
    if not isinstance(command, str) or not command.strip():
        return {"error": "command cannot be empty"}
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
        return {"error": "timeout must be a positive integer"}
    timeout = min(timeout, 300)
    cwd = tools.workspace_root().expanduser().resolve()
    if not cwd.is_dir():
        return {"error": f"Workspace directory not found: {cwd}"}
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        limit = 20_000
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": stdout[-limit:],
            "stderr": stderr[-limit:],
            "truncated": len(stdout) > limit or len(stderr) > limit,
            "passed": completed.returncode == 0,
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return {
            "command": command,
            "returncode": None,
            "stdout": stdout[-20_000:],
            "stderr": stderr[-20_000:],
            "passed": False,
            "timed_out": True,
            "error": f"timed out after {timeout} seconds",
        }
    except OSError as exc:
        return {"command": command, "returncode": None, "passed": False, "error": str(exc)}

