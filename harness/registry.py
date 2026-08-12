"""Tool registry, prompt, and invocation parsing."""

import inspect
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from harness.tools import ALL_TOOLS, TOOL_REGISTRY

SYSTEM_PROMPT = """
You are a coding assistant. Tools:

{tool_list}

When you need a tool, reply with exactly one line:
tool: TOOL_NAME({{JSON_ARGS}})
JSON_ARGS must be valid JSON with double-quoted keys.
After a tool_result, continue the task. Otherwise reply normally.
""".strip()

_UNQUOTED_JSON_KEY_RE = re.compile(r"([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s*:)")


def get_full_system_prompt() -> str:
    parts = []
    for name, func in ALL_TOOLS:
        parts.append(
            f"TOOL\n===\nName: {name}\nDescription: {func.__doc__}\n"
            f"Signature: {inspect.signature(func)}\n{'=' * 15}"
        )
    return SYSTEM_PROMPT.format(tool_list="\n\n".join(parts))


def _parse_args(json_str: str) -> Optional[Dict[str, Any]]:
    try:
        obj = json.loads(json_str)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        fixed = _UNQUOTED_JSON_KEY_RE.sub(r'\1"\2"\3', json_str)
        try:
            obj = json.loads(fixed)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None


def extract_tool_invocations(text: str) -> List[Tuple[str, Dict[str, Any]]]:
    invocations = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("tool:"):
            continue
        try:
            after = line[len("tool:") :].strip()
            name, rest = after.split("(", 1)
            name, rest = name.strip(), rest.rstrip()
            if not rest.endswith(")"):
                continue
            args = _parse_args(rest[:-1].strip())
            if args is not None:
                invocations.append((name, args))
        except Exception:
            continue
    return invocations


def execute_tool(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    tool = TOOL_REGISTRY.get(tool_name)
    if not tool:
        return {"error": f"Unknown tool: {tool_name}"}
    if tool_name == "read_file":
        return tool(args.get("filename", "."))
    if tool_name == "list_files":
        return tool(args.get("path", "."))
    if tool_name == "edit_file":
        return tool(args.get("path", "."), args.get("old_str", ""), args.get("new_str", ""))
    return {"error": "Unhandled tool"}


def format_tool_user_message(tool_name: str, result: Dict[str, Any]) -> str:
    if tool_name == "read_file":
        return (
            f"tool_result(read_file) file_path={result.get('file_path', '')}\n"
            "---- FILE START ----\n"
            f"{result.get('content', '')}\n"
            "---- FILE END ----\n"
        )
    return f"tool_result({json.dumps(result, ensure_ascii=False)})"
