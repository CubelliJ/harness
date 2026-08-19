"""Conversation helpers and history."""

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

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


def estimate_tokens(message: Dict[str, Any]) -> int:
    """Estimate a message's tokens without requiring a model tokenizer.

    Four characters per token is intentionally conservative for source code and
    tool output. The fixed overhead accounts for chat message framing.
    """
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    return max(1, (len(payload) + 3) // 4 + 4)


def compact_conversation(
    conversation: List[Dict[str, Any]],
    budget: Optional[int],
    token_counter: Callable[[Dict[str, Any]], int] = estimate_tokens,
    force: bool = False,
) -> bool:
    """Prune old turns until ``conversation`` fits within ``budget``.

    With ``force=True``, remove the oldest complete turn even when the
    conversation is already within its automatic compaction budget. This is
    used by the manual ``/compact`` command and does not require a provider
    context limit. The system prompt is always retained, and eviction happens
    only at complete user turns so assistant tool calls stay paired with their
    tool results. Returns whether anything was compacted.
    """
    if not conversation or (not force and (
        budget is None or budget < 1 or sum(token_counter(m) for m in conversation) <= budget
    )):
        return False

    system = conversation[:1]
    rest = conversation[1:]
    user_boundaries = [
        index for index, message in enumerate(rest)
        if message.get("role") == "user"
    ]
    # Preserve the newest user turn. Manual compaction removes one older turn;
    # automatic compaction removes as many older turns as the budget requires.
    if len(user_boundaries) < (2 if force else 1):
        return False
    if force:
        start = user_boundaries[1]
    else:
        start = user_boundaries[-1]
        for boundary in user_boundaries[1:]:
            if sum(token_counter(m) for m in system + rest[boundary:]) <= budget:
                start = boundary
                break

    removed = rest[:start]
    if not removed:
        return False
    summary = {
        "role": "system",
        "content": "[Earlier conversation compacted: %d messages omitted. Continue from the retained history.]"
                   % len(removed),
    }
    conversation[:] = system + [summary] + rest[start:]
    logger.info("compacted conversation: removed %d messages", len(removed))
    return True
