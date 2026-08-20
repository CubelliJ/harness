"""OpenRouter chat client with native tool calling."""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from harness.config import (
    OPENROUTER_CHAT_URL,
    MODEL_METADATA_TIMEOUT_S,
    OPENROUTER_MODELS_URL,
    REQUEST_TIMEOUT_S,
    get_model,
)
from harness.registry import OPENAI_TOOLS

logger = logging.getLogger(__name__)

ASSISTANT_PREFIX = "\u001b[92m▸ Assistant:\u001b[0m "
MAX_RETRIES = 5
RETRY_BASE_S = 2.0
TITLE_MAX_INPUT_CHARS = 1200
TITLE_MAX_OUTPUT_TOKENS = 16


def _models_response() -> Dict[str, Any]:
    """Fetch the model catalogue from OpenRouter."""
    with urllib.request.urlopen(
        urllib.request.Request(OPENROUTER_MODELS_URL, headers=_headers()),
        timeout=MODEL_METADATA_TIMEOUT_S,
    ) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict):
        raise ValueError("OpenRouter models response is not an object")
    return body


def get_available_models() -> List[Dict[str, Any]]:
    """Return usable model records from OpenRouter's model catalogue."""
    body = _models_response()
    models = []
    for model in body.get("data") or []:
        if isinstance(model, dict) and isinstance(model.get("id"), str) and model["id"].strip():
            models.append(model)
    return sorted(models, key=lambda model: (model.get("name") or model["id"]).lower())


def get_model_context_length() -> Optional[int]:
    """Return the provider-reported context limit for the configured model."""
    try:
        return model_context_length(_models_response(), get_model())
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("Could not retrieve model context length: %s", exc)
    return None


def model_context_length(body: Dict[str, Any], model_id: str) -> Optional[int]:
    """Extract a provider-reported context limit from a models response."""
    for model in body.get("data") or []:
        if model.get("id") == model_id:
            limit = model.get("context_length")
            return int(limit) if limit is not None else None
    return None


def _is_rate_limited(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "429" in text or "rate-limited" in text or "rate limit" in text


def _retry_after_s(attempt: int) -> float:
    return RETRY_BASE_S * (2 ** attempt)


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
) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    """
    Non-streaming chat completion with native tools.

    Returns (assistant_text, tool_calls, usage). ``usage`` contains the
    provider-reported token counts, including ``prompt_tokens`` for context.
    Retries transient OpenRouter rate limits with exponential backoff.
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
    t0 = time.perf_counter()
    last_error: Optional[BaseException] = None

    for attempt in range(MAX_RETRIES):
        request = urllib.request.Request(
            OPENROUTER_CHAT_URL, data=payload, method="POST", headers=_headers()
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"OpenRouter HTTP {e.code}: {detail}")
            if e.code == 429 and attempt < MAX_RETRIES - 1:
                wait = _retry_after_s(attempt)
                print(f"\033[90m▸ rate limited; retrying in {wait:.0f}s…\033[0m")
                time.sleep(wait)
                continue
            raise last_error from e

        if body.get("error"):
            last_error = RuntimeError(f"OpenRouter error: {body['error']}")
            if _is_rate_limited(last_error) and attempt < MAX_RETRIES - 1:
                wait = _retry_after_s(attempt)
                print(f"\033[90m▸ rate limited; retrying in {wait:.0f}s…\033[0m")
                time.sleep(wait)
                continue
            raise last_error

        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError(f"OpenRouter: empty choices: {body!r}")

        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []
        usage = body.get("usage") or {}

        logger.debug(
            "OpenRouter OK in %.2fs chars=%d tool_calls=%d",
            time.perf_counter() - t0,
            len(content),
            len(tool_calls),
        )
        return content, tool_calls, usage

    assert last_error is not None
    raise last_error


def generate_conversation_title(conversation: List[Dict[str, Any]]) -> str:
    """Generate a short title from a bounded conversation excerpt.

    This intentionally uses a separate tool-free request and never sends the
    full conversation or tool output to the provider.
    """
    excerpt: List[str] = []
    for message in conversation:
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = str(message.get("content") or "").strip()
        if content:
            excerpt.append(f"{role}: {content}")
    prompt = "\n".join(excerpt)[-TITLE_MAX_INPUT_CHARS:]
    if not prompt:
        return "New conversation"
    payload = json.dumps({
        "model": get_model(),
        "messages": [
            {"role": "system", "content": (
                "Give this coding conversation a concise title of 2-6 words. "
                "Return only the title, with no quotes or punctuation at the end."
            )},
            {"role": "user", "content": prompt},
        ],
        "tools": [],
        "tool_choice": "none",
        "max_tokens": TITLE_MAX_OUTPUT_TOKENS,
        "stream": False,
    }).encode()
    request = urllib.request.Request(
        OPENROUTER_CHAT_URL, data=payload, method="POST", headers=_headers()
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
        body = json.loads(response.read().decode("utf-8"))
    if body.get("error"):
        raise RuntimeError(f"OpenRouter error: {body['error']}")
    content = ((body.get("choices") or [{}])[0].get("message") or {}).get("content")
    title = " ".join(str(content or "").split()).strip(" .:-")
    return title[:60] or "New conversation"


def parse_tool_call(tool_call: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any]]:
    """Return a validated ``(call_id, name, args_dict)`` tuple.

    Tool calls come from the model, so malformed payloads must fail closed. In
    particular, silently turning invalid arguments into ``{}`` can cause a
    tool's defaults to perform an unintended operation.
    """
    if not isinstance(tool_call, dict):
        raise ValueError("tool call must be an object")
    call_id = tool_call.get("id")
    if not isinstance(call_id, str) or not call_id.strip():
        raise ValueError("tool call is missing a valid id")
    fn = tool_call.get("function")
    if not isinstance(fn, dict):
        raise ValueError("tool call is missing its function")
    name = fn.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("tool call is missing a function name")
    raw_args = fn.get("arguments", "{}")
    if isinstance(raw_args, dict):
        args = raw_args
    elif isinstance(raw_args, str):
        try:
            args = json.loads(raw_args or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"tool call has invalid JSON arguments: {exc.msg}") from exc
    else:
        raise ValueError("tool call arguments must be a JSON object")
    if not isinstance(args, dict):
        raise ValueError("tool call arguments must decode to an object")
    return call_id, name, args
