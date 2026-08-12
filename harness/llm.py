"""OpenRouter chat client with native tool calling."""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Tuple

from harness.config import OPENROUTER_CHAT_URL, REQUEST_TIMEOUT_S, get_model
from harness.registry import OPENAI_TOOLS

logger = logging.getLogger(__name__)

ASSISTANT_PREFIX = "\u001b[92m▸ Assistant:\u001b[0m "


def _headers() -> Dict[str, str]:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add it to your environment or `.env` file."
        )
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }


def _api_messages(conversation: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pass through OpenAI-compatible message fields needed for tool calling."""
    out: List[Dict[str, Any]] = []
    for msg in conversation:
        role = msg.get("role", "user")
        if role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.get("tool_call_id", ""),
                    "content": msg.get("content") or "",
                }
            )
            continue
        item: Dict[str, Any] = {"role": role if role in ("system", "user", "assistant") else "user"}
        content = msg.get("content")
        if content is not None:
            item["content"] = content
        elif role == "assistant" and msg.get("tool_calls"):
            item["content"] = None
        else:
            item["content"] = ""
        if role == "assistant" and msg.get("tool_calls"):
            item["tool_calls"] = msg["tool_calls"]
        out.append(item)
    return out


def execute_llm_call(
    conversation: List[Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Non-streaming chat completion with native tools.

    Returns (assistant_text, tool_calls). tool_calls is empty when the model
    is done talking; otherwise each entry is an OpenAI tool_call object.
    """
    model = get_model()
    payload = json.dumps(
        {
            "model": model,
            "messages": _api_messages(conversation),
            "tools": OPENAI_TOOLS,
            "tool_choice": "auto",
            "stream": False,
        }
    ).encode()
    request = urllib.request.Request(
        OPENROUTER_CHAT_URL, data=payload, method="POST", headers=_headers()
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenRouter HTTP {e.code}: {detail}") from e

    if body.get("error"):
        raise RuntimeError(f"OpenRouter error: {body['error']}")

    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError(f"OpenRouter: empty choices: {body!r}")

    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    tool_calls = message.get("tool_calls") or []

    logger.debug(
        "OpenRouter OK in %.2fs chars=%d tool_calls=%d",
        time.perf_counter() - t0,
        len(content),
        len(tool_calls),
    )
    return content, tool_calls


def parse_tool_call(tool_call: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any]]:
    """Return (call_id, name, args_dict) from an OpenAI tool_call object."""
    call_id = tool_call.get("id") or ""
    fn = tool_call.get("function") or {}
    name = fn.get("name") or ""
    raw_args = fn.get("arguments") or "{}"
    try:
        args = json.loads(raw_args)
        if not isinstance(args, dict):
            args = {}
    except json.JSONDecodeError:
        args = {}
    return call_id, name, args
