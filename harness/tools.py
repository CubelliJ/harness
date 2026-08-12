"""Barebones file tools: read, list, edit."""

from pathlib import Path
from typing import Any, Dict

from harness.config import workspace_root


def resolve_abs_path(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = (workspace_root() / path).resolve()
    return path


def read_file(filename: str) -> Dict[str, Any]:
    """Read a file and return its full content."""
    full_path = resolve_abs_path(filename)
    return {"file_path": str(full_path), "content": full_path.read_text(encoding="utf-8")}


def list_files(path: str = ".") -> Dict[str, Any]:
    """List files and directories at path."""
    full_path = resolve_abs_path(path)
    return {
        "path": str(full_path),
        "files": [
            {"filename": item.name, "type": "file" if item.is_file() else "dir"}
            for item in full_path.iterdir()
        ],
    }


def edit_file(path: str, old_str: str, new_str: str) -> Dict[str, Any]:
    """Replace first occurrence of old_str with new_str. Empty old_str creates/overwrites the file."""
    full_path = resolve_abs_path(path)
    if old_str == "":
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(new_str, encoding="utf-8")
        return {"path": str(full_path), "action": "created_file"}
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
