"""Tool schemas, execution, and result formatting."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from harness.skills import load_skill, skill_catalog
from harness.tools import TOOL_REGISTRY

SYSTEM_PROMPT = """
You are a coding assistant with local file tools for this Python repo.
Use tools to inspect, edit, and test files. After meaningful edits, use run_command
when appropriate to run focused tests or validation. Prefer harness/*.py and README.md.
Do not claim tools are unavailable — call them.
Before every run_command call, briefly explain what you will run and why in at most two lines.
When a relevant workspace skill is listed, load it with load_skill before relying on it.
Be brief on the answers.
""".strip()

# OpenAI/OpenRouter function-calling schemas
OPENAI_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": "Load a relevant skill explicitly linked from AGENTS.md.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill": {
                        "type": "string",
                        "description": "Skill name or relative path from the available skills catalog",
                    }
                },
                "required": ["skill"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file and return its full content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Path to the file relative to the workspace",
                    }
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command in the workspace, such as tests or a formatter, and return bounded output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to run from the workspace root"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds, maximum 300", "default": 120},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories at a path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path relative to the workspace",
                        "default": ".",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Recursively search text files under the workspace, honoring .gitignore.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Case-insensitive text to find"},
                    "path": {"type": "string", "description": "Directory relative to the workspace", "default": "."},
                    "glob": {"type": "string", "description": "Filename pattern, such as *.py", "default": "*"},
                    "max_results": {"type": "integer", "description": "Maximum matches to return", "default": 100},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Replace the first occurrence of old_str with new_str. "
                "Empty old_str creates or overwrites the file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "old_str": {"type": "string", "description": "Text to replace"},
                    "new_str": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old_str", "new_str"],
            },
        },
    },
    {
        "type": "function", "function": {"name": "git_status",
        "description": "Show concise Git working-tree status (read-only).",
        "parameters": {"type": "object", "properties": {}}}},
    {
        "type": "function", "function": {"name": "git_diff",
        "description": "Inspect unstaged or staged Git diff (read-only).",
        "parameters": {"type": "object", "properties": {
            "staged": {"type": "boolean", "default": False},
            "path": {"type": "string", "description": "Optional workspace-relative path"},
        }}}},
    {
        "type": "function", "function": {"name": "git_log",
        "description": "Show recent Git commits, optionally for one workspace path (read-only).",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            "path": {"type": "string", "description": "Optional workspace-relative path"},
        }}}},
    {
        "type": "function", "function": {"name": "git_branch_list",
        "description": "List local and remote Git branches (read-only).",
        "parameters": {"type": "object", "properties": {}}}},
]


def get_full_system_prompt(workspace: Optional[Path] = None) -> str:
    """Return built-in guidance plus workspace-specific AGENTS.md instructions."""
    if workspace is None:
        return SYSTEM_PROMPT
    agents_file = workspace / "AGENTS.md"
    try:
        instructions = agents_file.read_text(encoding="utf-8").strip()
    except OSError:
        instructions = ""
    if not instructions:
        return SYSTEM_PROMPT
    prompt = f"{SYSTEM_PROMPT}\n\nWorkspace instructions from {agents_file}:\n{instructions}"
    catalog = skill_catalog(workspace)
    return f"{prompt}\n\n{catalog}" if catalog else prompt


def execute_tool(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a tool after validating model-supplied arguments.

    Required fields are checked here rather than relying on ``dict.get``
    defaults. This keeps malformed calls from turning into filesystem actions.
    """
    tool = load_skill if tool_name == "load_skill" else TOOL_REGISTRY.get(tool_name)
    if not tool:
        return {"error": f"Unknown tool: {tool_name}"}
    if not isinstance(args, dict):
        return {"error": "Tool arguments must be an object"}
    required = {
        "load_skill": ("skill",),
        "read_file": ("filename",),
        "run_command": ("command",),
        "search_files": ("query",),
        "edit_file": ("path", "old_str", "new_str"),
    }.get(tool_name, ())
    missing = [key for key in required if key not in args]
    if missing:
        return {"error": f"Missing required argument(s): {', '.join(missing)}"}
    try:
        if tool_name == "load_skill":
            return load_skill(args["skill"])
        if tool_name == "read_file":
            return tool(args["filename"])
        if tool_name == "run_command":
            return tool(args["command"], args.get("timeout", 120))
        if tool_name == "list_files":
            return tool(args.get("path", "."))
        if tool_name == "search_files":
            return tool(
                args["query"], args.get("path", "."), args.get("glob", "*"),
                args.get("max_results", 100),
            )
        if tool_name == "edit_file":
            # ``apply`` is an internal execution flag and is intentionally not
            # exposed in the model-facing schema.
            return tool(args["path"], args["old_str"], args["new_str"],
                        apply=args.get("apply", True))
        if tool_name == "git_diff":
            return tool(args.get("staged", False), args.get("path", ""))
        if tool_name == "git_log":
            return tool(args.get("limit", 20), args.get("path", ""))
        if tool_name in {"git_status", "git_branch_list"}:
            return tool()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    return {"error": "Unhandled tool"}


def format_tool_result_content(tool_name: str, result: Dict[str, Any]) -> str:
    """Plain text/JSON content for a role=tool message."""
    if result.get("error"):
        return json.dumps({"error": result["error"]}, ensure_ascii=False)
    if tool_name == "load_skill":
        return (
            f"skill={result.get('name', '')} path={result.get('path', '')}\n"
            "---- SKILL START ----\n"
            f"{result.get('content', '')}\n"
            "---- SKILL END ----"
        )
    if tool_name == "read_file":
        return (
            f"file_path={result.get('file_path', '')}\n"
            "---- FILE START ----\n"
            f"{result.get('content', '')}\n"
            "---- FILE END ----"
        )
    if tool_name == "list_files":
        files = result.get("files") or []
        listing = "\n".join(
            f"- {item.get('filename')} ({item.get('type')})" for item in files
        )
        return f"path={result.get('path', '')}\n{listing}"
    return json.dumps(result, ensure_ascii=False)
