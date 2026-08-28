"""Tool implementations grouped by responsibility.

The package facade preserves the historical ``harness.tools`` import surface.
"""

from harness.config import workspace_root
from .filesystem import (
    resolve_abs_path, read_file, read_image, list_files, search_files,
    edit_preview, edit_file,
)
from .shell import run_command
from .git import (
    _limit_diff_per_file,
    git_status,
    git_diff,
    git_log,
    git_branch_list,
)

ALL_TOOLS = [
    ("read_file", read_file),
    ("read_image", read_image),
    ("run_command", run_command),
    ("list_files", list_files),
    ("search_files", search_files),
    ("edit_file", edit_file),
    ("git_status", git_status),
    ("git_diff", git_diff),
    ("git_log", git_log),
    ("git_branch_list", git_branch_list),
]

TOOL_REGISTRY = dict(ALL_TOOLS)
