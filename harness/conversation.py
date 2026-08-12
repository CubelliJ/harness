"""Conversation helpers and history."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

YOU_PROMPT = "\u001b[96m▸ You:\u001b[0m "
ASSISTANT_PREFIX = "\u001b[92m▸ Assistant:\u001b[0m "


def _format_message(msg: Dict[str, Any]) -> str:
    role = msg.get("role", "?")
    content = msg.get("content") or ""
    extra = ""
    if msg.get("tool_calls"):
        extra = "\n" + json.dumps(msg["tool_calls"], ensure_ascii=False, indent=2)
    if msg.get("tool_call_id"):
        extra = f"\ntool_call_id={msg['tool_call_id']}" + extra
    return f"{'=' * 12} {role} {'=' * 12}\n{content}{extra}\n"


def save_conversation_history(path: Path, conversation: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(_format_message(m) for m in conversation), encoding="utf-8")
    logger.debug("wrote history %s (%d messages)", path, len(conversation))


def system_message(content: str) -> Dict[str, Any]:
    return {"role": "system", "content": content}


def user_message(content: str) -> Dict[str, Any]:
    return {"role": "user", "content": content.strip()}


def assistant_message(
    content: Optional[str] = None,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    msg: Dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def tool_message(tool_call_id: str, content: str) -> Dict[str, Any]:
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}
