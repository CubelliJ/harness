"""Tool schemas, execution, and result formatting."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from harness.tools import TOOL_REGISTRY

SYSTEM_PROMPT = """
You are a coding assistant with local file tools for this Python repo.
Use tools to inspect, edit, and test files. After meaningful edits, use run_command
when appropriate to run focused tests or validation. Prefer harness/*.py and README.md.
Do not claim tools are unavailable — call them.
Before every run_command call, briefly explain what you will run and why in at most two lines.
Be brief on the answers.
""".strip()

# OpenAI/OpenRouter function-calling schemas
OPENAI_TOOLS: List[Dict[str, Any]] = [
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
    return f"{SYSTEM_PROMPT}\n\nWorkspace instructions from {agents_file}:\n{instructions}"


def execute_tool(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a tool after validating model-supplied arguments.

    Required fields are checked here rather than relying on ``dict.get``
    defaults. This keeps malformed calls from turning into filesystem actions.
    """
    tool = TOOL_REGISTRY.get(tool_name)
    if not tool:
        return {"error": f"Unknown tool: {tool_name}"}
    if not isinstance(args, dict):
        return {"error": "Tool arguments must be an object"}
    required = {
        "read_file": ("filename",),
        "run_command": ("command",),
        "search_files": ("query",),
        "edit_file": ("path", "old_str", "new_str"),
    }.get(tool_name, ())
    missing = [key for key in required if key not in args]
    if missing:
        return {"error": f"Missing required argument(s): {', '.join(missing)}"}
    try:
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
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    return {"error": "Unhandled tool"}


def format_tool_result_content(tool_name: str, result: Dict[str, Any]) -> str:
    """Plain text/JSON content for a role=tool message."""
    if result.get("error"):
        return json.dumps({"error": result["error"]}, ensure_ascii=False)
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
