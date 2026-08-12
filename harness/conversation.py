"""Conversation helpers and history."""

import logging
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

YOU_PROMPT = "\u001b[96m▸ You:\u001b[0m "
ASSISTANT_PREFIX = "\u001b[92m▸ Assistant:\u001b[0m "


def save_conversation_history(path: Path, conversation: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = [
        f"{'=' * 12} {msg['role']} {'=' * 12}\n{msg.get('content', '')}\n"
        for msg in conversation
    ]
    path.write_text("\n".join(blocks), encoding="utf-8")
    logger.debug("wrote history %s (%d messages)", path, len(conversation))


def system_message(content: str) -> Dict[str, str]:
    return {"role": "system", "content": content}


def user_message(content: str) -> Dict[str, str]:
    return {"role": "user", "content": content.strip()}


def assistant_message(content: str) -> Dict[str, str]:
    return {"role": "assistant", "content": content}
