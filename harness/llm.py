"""OpenRouter chat client."""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Tuple

from harness.config import OPENROUTER_CHAT_URL, REQUEST_TIMEOUT_S, get_model

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


def _consume_sse(response: Any, on_delta: Callable[[str], None]) -> str:
    parts: List[str] = []
    while True:
        line = response.readline()
        if not line:
            break
        if line.startswith(b":"):
            continue
        s = line.strip()
        if not s or not s.startswith(b"data:"):
            continue
        payload = s[len(b"data:") :].strip()
        if payload == b"[DONE]":
            break
        try:
            obj = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError:
            continue
        if obj.get("error"):
            raise RuntimeError(f"OpenRouter error: {obj['error']}")
        for ch in obj.get("choices") or []:
            piece = (ch.get("delta") or {}).get("content") or ""
            if piece:
                parts.append(piece)
                on_delta(piece)
    return "".join(parts)


def execute_llm_call(conversation: List[Dict[str, str]]) -> Tuple[str, bool]:
    """Stream a chat completion. Returns (text, already_printed)."""
    model = get_model()
    messages = [
        {"role": m["role"] if m["role"] in ("system", "user", "assistant") else "user",
         "content": m["content"]}
        for m in conversation
    ]
    payload = json.dumps({"model": model, "messages": messages, "stream": True}).encode()
    request = urllib.request.Request(
        OPENROUTER_CHAT_URL, data=payload, method="POST", headers=_headers()
    )
    t0 = time.perf_counter()
    printed = False
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            print(ASSISTANT_PREFIX, end="", flush=True)
            printed = True
            text = _consume_sse(response, lambda d: print(d, end="", flush=True))
            print()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenRouter HTTP {e.code}: {detail}") from e
    logger.debug("OpenRouter OK in %.2fs chars=%d", time.perf_counter() - t0, len(text))
    return text, printed
