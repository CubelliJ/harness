"""Conversation helpers and history."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# Small visual cues keep the REPL feeling alive without changing its behavior.
YOU_PROMPT = "\u001b[96m◆ You\u001b[0m  "
ASSISTANT_PREFIX = "\u001b[92m◆ Assistant\u001b[0m  "


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


def session_catalog_path(state_path: Path) -> Path:
    """Return the catalogue path for sessions in the same log directory."""
    return state_path.parent / "sessions.json"


def conversation_title(conversation: Sequence[Dict[str, Any]]) -> str:
    """Create a short display title from the first user request."""
    for message in conversation:
        if message.get("role") == "user":
            text = " ".join(str(message.get("content") or "").split())
            if text:
                return text[:57] + "..." if len(text) > 60 else text
    return "New conversation"


def save_session_catalog(path: Path, sessions: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"version": 1, "sessions": sessions},
                         ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_session_catalog(path: Path, workspace: Optional[Path] = None) -> List[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        sessions = payload["sessions"]
        if payload.get("version") != 1 or not isinstance(sessions, list):
            raise ValueError("invalid session catalogue")
        valid = [s for s in sessions if isinstance(s, dict) and s.get("path")]
        if workspace is None:
            return valid
        workspace_name = str(workspace.resolve())
        return [s for s in valid if s.get("workspace") == workspace_name]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return []


def update_session_catalog(
    path: Path, state_path: Path, conversation: Sequence[Dict[str, Any]],
    title: Optional[str] = None, workspace: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Record a session, retaining five recent sessions per workspace."""
    sessions = load_session_catalog(path)
    workspace_name = str((workspace or Path.cwd()).resolve())
    entry = {
        "path": str(state_path),
        "workspace": workspace_name,
        "title": title or conversation_title(conversation),
        "updated": datetime.now().isoformat(timespec="seconds"),
    }
    sessions = [s for s in sessions if s.get("path") != str(state_path)]
    workspace_sessions = [s for s in sessions if s.get("workspace") == workspace_name]
    other_sessions = [s for s in sessions if s.get("workspace") != workspace_name]
    workspace_sessions.insert(0, entry)
    sessions = other_sessions + workspace_sessions[:5]
    save_session_catalog(path, sessions)
    return workspace_sessions[:5]


def session_state_path(history_path: Path) -> Path:
    """Return the structured state path associated with a readable history."""
    return history_path.with_suffix(".json")


def save_conversation_state(path: Path, conversation: List[Dict[str, Any]]) -> None:
    """Persist messages in the provider-compatible format used for resume."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"version": 1, "conversation": conversation},
                         ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
    logger.debug("wrote session state %s (%d messages)", path, len(conversation))


def load_conversation_state(path: Path) -> Optional[List[Dict[str, Any]]]:
    """Load a previously persisted conversation, or return ``None`` if absent/invalid."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        conversation = payload["conversation"]
        if payload.get("version") != 1 or not isinstance(conversation, list):
            raise ValueError("unsupported session state")
        if not all(isinstance(message, dict) and message.get("role") for message in conversation):
            raise ValueError("invalid conversation messages")
        return conversation
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        if path.exists():
            logger.warning("could not resume session from %s: %s", path, exc)
        return None


def system_message(content: str) -> Dict[str, Any]:
    return {"role": "system", "content": content}


def user_message(content: str) -> Dict[str, Any]:
    return {"role": "user", "content": content.strip()}


def assistant_message(
    content: Optional[str] = None,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    usage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    msg: Dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    if usage:
        # Usage is metadata for Harness only; llm._api_messages deliberately
        # omits it when rebuilding provider-compatible messages.
        msg["usage"] = usage
    return msg


def _usage_number(usage: Dict[str, Any], key: str) -> int:
    value = usage.get(key, 0)
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number >= 0 else 0


def conversation_cost(conversation: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate provider-reported usage retained on assistant messages."""
    calls = 0
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    cost = 0.0
    cost_known = True
    last: Optional[Dict[str, Any]] = None
    for message in conversation:
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        calls += 1
        prompt_tokens += _usage_number(usage, "prompt_tokens")
        completion_tokens += _usage_number(usage, "completion_tokens")
        total_tokens += _usage_number(usage, "total_tokens")
        raw_cost = usage.get("cost")
        try:
            if raw_cost is None:
                raise ValueError
            cost += float(raw_cost)
        except (TypeError, ValueError):
            cost_known = False
        last = usage
    return {
        "calls": calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cost": cost if cost_known else None,
        "last_usage": last,
    }


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
