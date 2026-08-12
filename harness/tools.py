"""Barebones file tools: read, list, edit."""

import difflib
import fnmatch
import hashlib
import os
import stat
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from harness.config import workspace_root


def resolve_abs_path(path_str: str) -> Path:
    """Resolve a path and ensure it remains inside the configured workspace.

    ``Path.resolve`` is used before validation so that both ``..`` traversal
    and symlinks pointing outside the workspace are rejected. ``strict=False``
    allows ``edit_file`` to create a new file that does not exist yet.
    """
    root = workspace_root().expanduser().resolve()
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve(strict=False)

    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"Path escapes the configured workspace: {path_str!r}"
        ) from exc

    return resolved


def read_file(filename: str) -> Dict[str, Any]:
    """Read a file and return its full content."""
    try:
        full_path = resolve_abs_path(filename)
    except ValueError as e:
        return {"error": str(e)}
    if not full_path.is_file():
        return {"error": f"File not found: {full_path}"}
    return {"file_path": str(full_path), "content": full_path.read_text(encoding="utf-8")}


def list_files(path: str = ".") -> Dict[str, Any]:
    """List files and directories at path."""
    try:
        full_path = resolve_abs_path(path)
    except ValueError as e:
        return {"error": str(e)}
    if not full_path.is_dir():
        return {"error": f"Directory not found: {full_path}"}
    return {
        "path": str(full_path),
        "files": [
            {"filename": item.name, "type": "file" if item.is_file() else "dir"}
            for item in full_path.iterdir()
        ],
    }


def _load_gitignore(root: Path) -> list[str]:
    """Load simple gitignore patterns from the workspace root."""
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return []
    try:
        return [
            line.strip() for line in gitignore.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    except (OSError, UnicodeDecodeError):
        return []


def _gitignored(relative_path: Path, patterns: list[str]) -> bool:
    """Apply the common .gitignore cases without requiring Git."""
    path = relative_path.as_posix()
    ignored = False
    for pattern in patterns:
        negated = pattern.startswith("!")
        pattern = pattern[1:] if negated else pattern
        directory_pattern = pattern.endswith("/")
        pattern = pattern.rstrip("/")
        if not pattern:
            continue
        if pattern.startswith("/"):
            matched = fnmatch.fnmatch(path, pattern[1:])
        elif "/" in pattern:
            matched = fnmatch.fnmatch(path, pattern)
        else:
            matched = any(fnmatch.fnmatch(part, pattern) for part in relative_path.parts)
        if matched and (directory_pattern or not relative_path.is_dir()):
            ignored = not negated
    return ignored


def search_files(
    query: str,
    path: str = ".",
    glob: str = "*",
    max_results: int = 100,
) -> Dict[str, Any]:
    """Recursively search text files, honoring the workspace .gitignore."""
    if not query:
        return {"error": "Search query cannot be empty"}
    if max_results < 1:
        return {"error": "max_results must be at least 1"}
    try:
        root = resolve_abs_path(path)
        workspace = workspace_root().resolve()
    except ValueError as e:
        return {"error": str(e)}
    if not root.is_dir():
        return {"error": f"Directory not found: {root}"}

    patterns = _load_gitignore(workspace)
    matches = []
    for candidate in sorted(root.rglob("*")):
        if not candidate.is_file() or not fnmatch.fnmatch(candidate.name, glob):
            continue
        relative = candidate.relative_to(workspace)
        if any(part in {".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "node_modules"}
               for part in relative.parts):
            continue
        if _gitignored(relative, patterns):
            continue
        try:
            # Avoid blocking the agent on large or binary files.
            if candidate.stat().st_size > 2 * 1024 * 1024:
                continue
            with candidate.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, 1):
                    if query.casefold() not in line.casefold():
                        continue
                    matches.append({"file": relative.as_posix(), "line": line_number,
                                    "text": line.rstrip("\n\r")})
                    if len(matches) >= max_results:
                        return {"query": query, "matches": matches, "truncated": True}
        except (OSError, UnicodeDecodeError):
            continue
    return {"query": query, "matches": matches, "truncated": False}


def edit_preview(path: str, old_str: str, new_str: str) -> Dict[str, Any]:
    """Validate an edit and return its proposed contents and unified diff."""
    try:
        full_path = resolve_abs_path(path)
    except ValueError as e:
        return {"error": str(e)}

    if old_str == "":
        original = "" if not full_path.exists() else full_path.read_text(encoding="utf-8")
        proposed = new_str
        action = "created_file" if not full_path.exists() else "overwritten_file"
    else:
        if not full_path.is_file():
            return {"error": f"File not found: {full_path}"}
        original = full_path.read_text(encoding="utf-8")
        matches = original.count(old_str)
        if not matches:
            return {"path": str(full_path), "action": "old_str not found", "matches": 0}
        proposed = original.replace(old_str, new_str, 1)
        action = "edited"

    diff = "".join(difflib.unified_diff(
        original.splitlines(keepends=True),
        proposed.splitlines(keepends=True),
        fromfile=str(full_path),
        tofile=str(full_path),
    ))
    return {
        "path": str(full_path), "action": action, "matches": original.count(old_str),
        "original": original, "proposed": proposed, "diff": diff,
    }


def edit_file(path: str, old_str: str, new_str: str, *, apply: bool = True) -> Dict[str, Any]:
    """Propose an edit, optionally applying it with a backup and atomic replace."""
    preview = edit_preview(path, old_str, new_str)
    if preview.get("error") or preview.get("action") == "old_str not found":
        return preview
    if not apply:
        preview.pop("original", None)
        preview.pop("proposed", None)
        preview["action"] = "dry_run"
        return preview

    full_path = Path(preview["path"])
    if full_path.exists():
        # Keep recovery copies completely outside the repository. Git remains
        # the durable/versioned history; these are local safety snapshots only.
        root = workspace_root().expanduser().resolve()
        relative = full_path.relative_to(root)
        backup_root = Path(os.environ.get(
            "HARNESS_BACKUP_DIR", "~/.harness/backups"
        )).expanduser()
        workspace_id = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup = backup_root / workspace_id / relative.parent / (
            relative.name + f".harness.bak.{stamp}"
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(preview["original"], encoding="utf-8")
        try:
            os.chmod(backup, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        preview["backup_path"] = str(backup)
    full_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{full_path.name}.", dir=str(full_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            temp_file.write(preview["proposed"])
        if full_path.exists():
            os.chmod(temp_name, stat.S_IMODE(full_path.stat().st_mode))
        os.replace(temp_name, full_path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    preview.pop("original", None)
    preview.pop("proposed", None)
    return preview


ALL_TOOLS = [
    ("read_file", read_file),
    ("list_files", list_files),
    ("search_files", search_files),
    ("edit_file", edit_file),
]

TOOL_REGISTRY = dict(ALL_TOOLS)
