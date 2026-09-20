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
PLAN_ASSISTANT_PREFIX = "\u001b[33m◆ Assistant\u001b[0m  "


def _format_message(msg: Dict[str, Any]) -> str:
    role = msg.get("role", "?")
    raw_content = msg.get("content")
    content = (json.dumps(raw_content, ensure_ascii=False, indent=2)
               if isinstance(raw_content, (list, dict)) else (raw_content or ""))
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


def user_message(content: Any, extra_parts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    if extra_parts:
        parts: List[Dict[str, Any]] = [{"type": "text", "text": str(content).strip()}]
        parts.extend(extra_parts)
        return {"role": "user", "content": parts}
    return {"role": "user", "content": str(content).strip()}


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


def _first_usage_number(usage: Dict[str, Any], *keys: str) -> int:
    """Read the first present non-negative numeric usage field."""
    for key in keys:
        if key in usage:
            return _usage_number(usage, key)
    return 0


def usage_cost_fields(usage: Dict[str, Any]) -> Dict[str, int]:
    """Normalize common provider token fields for cost accounting.

    OpenAI-compatible gateways commonly report ``prompt_tokens`` and nested
    ``prompt_tokens_details.cached_tokens``. Anthropic-compatible gateways may
    instead report ``input_tokens``, ``cache_read_input_tokens`` and
    ``cache_creation_input_tokens``. Keep the original usage object intact, but
    expose a stable accounting vocabulary for summaries and future pricing.
    """
    prompt_details = usage.get("prompt_tokens_details")
    prompt_details = prompt_details if isinstance(prompt_details, dict) else {}
    completion_details = usage.get("completion_tokens_details")
    completion_details = completion_details if isinstance(completion_details, dict) else {}
    input_tokens = _first_usage_number(usage, "prompt_tokens", "input_tokens")
    cache_read = _first_usage_number(
        usage, "cache_read_input_tokens", "cached_input_tokens", "cache_read_tokens",
    )
    if not cache_read:
        cache_read = _first_usage_number(prompt_details, "cached_tokens", "cache_read_input_tokens")
    cache_write = _first_usage_number(
        usage, "cache_creation_input_tokens", "cache_write_input_tokens", "cache_write_tokens",
    )
    if not cache_write:
        cache_write = _first_usage_number(prompt_details, "cache_write_tokens", "cache_creation_input_tokens")
    output_tokens = _first_usage_number(usage, "completion_tokens", "output_tokens")
    reasoning_tokens = _first_usage_number(
        usage, "reasoning_tokens", "reasoning_output_tokens",
    )
    if not reasoning_tokens:
        reasoning_tokens = _first_usage_number(completion_details, "reasoning_tokens")
    total_tokens = _first_usage_number(usage, "total_tokens")
    return {
        "input_tokens": input_tokens,
        "cache_read_input_tokens": cache_read,
        "cache_write_input_tokens": cache_write,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
    }


def _usage_cost_number(usage: Dict[str, Any], *keys: str) -> Optional[float]:
    """Read a provider-reported dollar amount without confusing it with tokens."""
    for key in keys:
        if key not in usage:
            continue
        try:
            value = float(usage[key])
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    return None


def usage_cost_breakdown(usage: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Normalize provider-reported dollar costs by billing category.

    Providers do not standardize this optional detail. OpenRouter commonly
    places it under ``cost_details``; other gateways may return the same fields
    at the top level. Missing categories remain ``None`` so the UI can say
    ``unknown`` instead of inventing a price allocation.
    """
    details = usage.get("cost_details")
    details = details if isinstance(details, dict) else {}
    sources = (details, usage)

    def find(*keys: str) -> Optional[float]:
        for source in sources:
            value = _usage_cost_number(source, *keys)
            if value is not None:
                return value
        return None

    return {
        "input_cost": find(
            "input_cost", "prompt_cost", "inference_input_cost", "upstream_inference_input_cost",
        ),
        "cache_read_cost": find(
            "cache_read_cost", "input_cache_read_cost", "cache_read_input_cost",
            "cache_read", "input_cache_read", "upstream_inference_cache_read_cost",
        ),
        "cache_write_cost": find(
            "cache_write_cost", "input_cache_write_cost", "cache_creation_input_cost",
            "cache_write", "input_cache_write", "upstream_inference_cache_write_cost",
        ),
        "output_cost": find(
            "output_cost", "completion_cost", "inference_output_cost", "upstream_inference_output_cost",
        ),
        "reasoning_cost": find("reasoning_cost", "reasoning_output_cost"),
    }


def estimated_usage_cost(
    usage: Dict[str, Any],
    *,
    input_cost_per_million: Optional[float] = None,
    cache_read_cost_per_million: Optional[float] = None,
    cache_write_cost_per_million: Optional[float] = None,
    output_cost_per_million: Optional[float] = None,
) -> Dict[str, Optional[float]]:
    """Estimate category dollars from token counts and explicit rates.

    Rates are USD per million tokens. Cache-read/write rates are intentionally
    separate because providers commonly price them differently. A missing rate
    leaves that category unknown.
    """
    fields = usage_cost_fields(usage)
    cached = fields["cache_read_input_tokens"]
    written = fields["cache_write_input_tokens"]
    fresh = max(0, fields["input_tokens"] - cached - written)

    def estimate(tokens: int, rate: Optional[float]) -> Optional[float]:
        return None if rate is None else tokens * rate / 1_000_000

    return {
        "input_cost": estimate(fresh, input_cost_per_million),
        "cache_read_cost": estimate(cached, cache_read_cost_per_million),
        "cache_write_cost": estimate(written, cache_write_cost_per_million),
        "output_cost": estimate(fields["output_tokens"], output_cost_per_million),
        "reasoning_cost": None,
    }


def conversation_cost(
    conversation: Sequence[Dict[str, Any]],
    *,
    input_cost_per_million: Optional[float] = None,
    cache_read_cost_per_million: Optional[float] = None,
    cache_write_cost_per_million: Optional[float] = None,
    output_cost_per_million: Optional[float] = None,
) -> Dict[str, Any]:
    """Aggregate usage and provider-reported or locally estimated costs."""
    calls = 0
    fields = {
        "input_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }
    cost_fields = {key: 0.0 for key in (
        "input_cost", "cache_read_cost", "cache_write_cost", "output_cost", "reasoning_cost",
    )}
    cost_reported = {key: True for key in cost_fields}
    cost = 0.0
    cost_known = True
    last: Optional[Dict[str, Any]] = None
    for message in conversation:
        usage = message.get("usage") or message.get("compaction_usage")
        if not isinstance(usage, dict):
            continue
        calls += 1
        normalized = usage_cost_fields(usage)
        for key in fields:
            fields[key] += normalized[key]
        breakdown = usage_cost_breakdown(usage)
        estimated = estimated_usage_cost(
            usage,
            input_cost_per_million=input_cost_per_million,
            cache_read_cost_per_million=cache_read_cost_per_million,
            cache_write_cost_per_million=cache_write_cost_per_million,
            output_cost_per_million=output_cost_per_million,
        )
        for key in cost_fields:
            amount = breakdown[key]
            if amount is None:
                amount = estimated[key]
            if amount is None:
                cost_reported[key] = False
            else:
                cost_fields[key] += amount
        raw_cost = usage.get("cost")
        try:
            if raw_cost is None:
                raise ValueError
            cost += float(raw_cost)
        except (TypeError, ValueError):
            cost_known = False
        last = usage
    # Preserve historical keys while making the detailed names canonical.
    return {
        "calls": calls,
        "prompt_tokens": fields["input_tokens"],
        "completion_tokens": fields["output_tokens"],
        "cached_input_tokens": fields["cache_read_input_tokens"],
        **fields,
        "cost": cost if cost_known else None,
        "cost_breakdown": {
            key: value if cost_reported[key] else None
            for key, value in cost_fields.items()
        },
        "last_usage": last,
    }


def tool_message(tool_call_id: str, content: str) -> Dict[str, Any]:
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


def estimate_tokens(message: Dict[str, Any]) -> int:
    """Estimate a message's tokens without requiring a model tokenizer.

    Four characters per token is intentionally conservative for source code and
    tool output. The fixed overhead accounts for chat message framing.
    """
    # Image bytes are base64-encoded in data URLs, but provider vision token
    # accounting is based on the image itself. Keep compaction conservative and
    # stable by charging the requested fixed estimate instead of payload size.
    content = message.get("content")
    if isinstance(content, list) and any(
        isinstance(part, dict) and part.get("type") in {"image_url", "image"}
        for part in content
    ):
        text_parts = [part.get("text", "") for part in content
                      if isinstance(part, dict) and part.get("type") == "text"]
        return 1000 + max(0, (len(" ".join(text_parts)) + 3) // 4) + 4
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    return max(1, (len(payload) + 3) // 4 + 4)


def compact_conversation(
    conversation: List[Dict[str, Any]],
    budget: Optional[int],
    token_counter: Callable[[Dict[str, Any]], int] = estimate_tokens,
    force: bool = False,
    summarize: Optional[Callable[[Sequence[Dict[str, Any]]], Any]] = None,
    on_start: Optional[Callable[[], None]] = None,
) -> bool:
    """Prune old turns until ``conversation`` fits within ``budget``.

    With ``force=True``, remove the oldest complete turn even when the
    conversation is already within its automatic compaction budget. This is
    used by the manual ``/compact`` command and does not require a provider
    context limit. When supplied, ``summarize`` receives the complete history
    before eviction and may return either summary text or ``(text, usage)``.
    The system prompt is always retained, and eviction happens only at
    complete user turns so assistant tool calls stay paired with their tool
    results. Returns whether anything was compacted.
    """
    if not conversation or (not force and (
        budget is None or budget < 1 or sum(token_counter(m) for m in conversation) <= budget
    )):
        return False

    system = conversation[:1]
    rest = conversation[1:]
    user_boundaries = [
        index for index, message in enumerate(rest)
        if message.get("role") == "user" and not message.get("image_context")
    ]
    # Preserve the newest user turn. Manual compaction removes all older
    # complete turns; automatic compaction removes as many older turns as the
    # budget requires.
    if len(user_boundaries) < (2 if force else 1):
        return False
    if force:
        start = user_boundaries[-1]
    else:
        start = user_boundaries[-1]
        for boundary in user_boundaries[1:]:
            if sum(token_counter(m) for m in system + rest[boundary:]) <= budget:
                start = boundary
                break

    removed = rest[:start]
    if not removed:
        return False
    if on_start is not None:
        on_start()

    summary_text = "[Earlier conversation compacted: %d messages omitted. Continue from the retained history.]" % len(removed)
    summary_usage: Optional[Dict[str, Any]] = None
    if summarize is not None:
        try:
            result = summarize(tuple(conversation))
            if isinstance(result, tuple):
                summary_text = str(result[0]).strip() or summary_text
                if len(result) > 1 and isinstance(result[1], dict):
                    summary_usage = result[1]
            else:
                summary_text = str(result).strip() or summary_text
        except Exception as exc:  # summarization must never break the session
            logger.warning("could not summarize conversation during compaction: %s", exc)

    summary: Dict[str, Any] = {
        "role": "system",
        "content": "[Conversation handover]\n" + summary_text,
    }
    if summary_usage:
        summary["compaction_usage"] = summary_usage
    conversation[:] = system + [summary] + rest[start:]
    logger.info("compacted conversation: removed %d messages", len(removed))
    return True
