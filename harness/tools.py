"""Barebones file tools: read, list, edit."""

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


def edit_file(path: str, old_str: str, new_str: str) -> Dict[str, Any]:
    """Replace first occurrence of old_str with new_str. Empty old_str creates/overwrites the file."""
    try:
        full_path = resolve_abs_path(path)
    except ValueError as e:
        return {"error": str(e)}
    if old_str == "":
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(new_str, encoding="utf-8")
        return {"path": str(full_path), "action": "created_file"}
    if not full_path.is_file():
        return {"error": f"File not found: {full_path}"}
    original = full_path.read_text(encoding="utf-8")
    if old_str not in original:
        return {"path": str(full_path), "action": "old_str not found"}
    full_path.write_text(original.replace(old_str, new_str, 1), encoding="utf-8")
    return {"path": str(full_path), "action": "edited"}


ALL_TOOLS = [
    ("read_file", read_file),
    ("list_files", list_files),
    ("edit_file", edit_file),
]

TOOL_REGISTRY = dict(ALL_TOOLS)
