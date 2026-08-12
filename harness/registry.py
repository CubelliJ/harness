"""Tool schemas, execution, and result formatting."""

import json
from typing import Any, Dict, List

from harness.tools import TOOL_REGISTRY

SYSTEM_PROMPT = """
You are a coding assistant with local file tools for this Python repo.
Use tools to inspect and edit files. Prefer harness/*.py and README.md.
Do not claim tools are unavailable — call them.
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


def get_full_system_prompt() -> str:
    return SYSTEM_PROMPT


def execute_tool(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    tool = TOOL_REGISTRY.get(tool_name)
    if not tool:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        if tool_name == "read_file":
            return tool(args.get("filename", "."))
        if tool_name == "list_files":
            return tool(args.get("path", "."))
        if tool_name == "edit_file":
            # ``apply`` is an internal execution flag and is intentionally not
            # exposed in the model-facing schema.
            return tool(
                args.get("path", "."),
                args.get("old_str", ""),
                args.get("new_str", ""),
                apply=args.get("apply", True),
            )
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
