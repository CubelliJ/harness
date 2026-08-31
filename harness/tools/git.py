"""Read-only Git inspection tools."""

import subprocess

from typing import Any, Dict

import harness.tools as tools
from .filesystem import resolve_abs_path


def _git_command(args: list[str]) -> Dict[str, Any]:
    """Run a Git subcommand without invoking a shell."""
    cwd = tools.workspace_root().expanduser().resolve()
    if not (cwd / ".git").exists():
        return {"error": "Workspace is not a Git repository"}
    try:
        completed = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}
    stdout, stderr = completed.stdout or "", completed.stderr or ""
    return {
        "args": args, "returncode": completed.returncode,
        "stdout": stdout[-20_000:], "stderr": stderr[-20_000:],
        "passed": completed.returncode == 0,
        "truncated": len(stdout) > 20_000 or len(stderr) > 20_000,
    }


def git_status() -> Dict[str, Any]:
    """Return concise working-tree status."""
    return _git_command(["status", "--short", "--branch"])


def _limit_diff_per_file(diff: str, limit: int) -> tuple[str, bool]:
    """Limit added/deleted lines in each file section of a unified diff."""
    output = []
    changes = 0
    truncated = False
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            changes = 0
        is_change = (line.startswith("+") and not line.startswith("+++")) or (
            line.startswith("-") and not line.startswith("---")
        )
        if is_change:
            if changes >= limit:
                truncated = True
                continue
            changes += 1
        output.append(line)
    if truncated:
        output.append(f"\n[diff truncated: maximum {limit} changed lines per file]\n")
    return "".join(output), truncated


def git_diff(staged: bool = False, path: str = "", max_changes_per_file: int = 100) -> Dict[str, Any]:
    """Return the working-tree or staged diff, bounded per file."""
    if (not isinstance(max_changes_per_file, int)
            or isinstance(max_changes_per_file, bool)
            or not 1 <= max_changes_per_file <= 1000):
        return {"error": "max_changes_per_file must be an integer between 1 and 1000"}
    args = ["diff"] + (["--cached"] if staged else [])
    if path:
        try:
            relative = resolve_abs_path(path).relative_to(tools.workspace_root().resolve())
        except (ValueError, OSError) as exc:
            return {"error": str(exc)}
        args += ["--", relative.as_posix()]
    result = _git_command(args)
    if result.get("passed") and result.get("stdout"):
        result["stdout"], limited = _limit_diff_per_file(
            result["stdout"], max_changes_per_file
        )
        result["truncated"] = result.get("truncated", False) or limited
    return result


def git_log(limit: int = 20, path: str = "") -> Dict[str, Any]:
    """Return recent commits, optionally limited to one workspace path."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return {"error": "limit must be a positive integer"}
    args = ["log", "--oneline", "--decorate", f"-n{min(limit, 100)}"]
    if path:
        try:
            relative = resolve_abs_path(path).relative_to(tools.workspace_root().resolve())
        except (ValueError, OSError) as exc:
            return {"error": str(exc)}
        args += ["--", relative.as_posix()]
    return _git_command(args)


def git_branch_list() -> Dict[str, Any]:
    """Return local and remote branches with the current branch marked."""
    return _git_command(["branch", "--all", "--no-color"])

