"""Main entry point and agent loop."""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import termios
import tty
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from harness import config, get_version
from harness.config import (
    CONTEXT_COMPACTION_CAP,
    CONTEXT_COMPACTION_RATIO,
    history_file_path,
)
from harness.conversation import (
    compact_conversation,
    conversation_cost,
    YOU_PROMPT,
    conversation_title,
    load_conversation_state,
    load_session_catalog,
    save_conversation_state,
    session_catalog_path,
    update_session_catalog,
    save_conversation_history,
    session_state_path,
    system_message,
    tool_message,
    user_message,
)
from harness.cli.agent_loop import _append_interrupted_tool_results, run_turn
from harness.cli.input import (
    AgentInterrupted,
    _drain_pending_input,
    _interruptible_call,
    _read_input,
)
from harness.cli.confirmations import (
    colorize_diff,
    confirm_command,
    confirm_edit,
    read_confirmation,
)
from harness.cli.voice_ui import (
    clear_voice_display,
    pause_voice_session,
    rows_for_voice_line,
    terminal_width,
    visible_len,
    voice_loop,
)
from harness.llm import (
    filter_models,
    get_available_models,
    get_model_context_length,
    generate_conversation_title,
)
from harness.registry import get_full_system_prompt
from harness.terminal import render_markdown
from harness.voice import VoiceSession

logger = logging.getLogger(__name__)


from harness.cli.presentation import (
    _banner,
    _context_bar,
    _format_model_context,
    _format_tokens,
    _git_branch,
    _offer_workspace_default,
    _print_context,
    _print_cost,
    _prompt,
    _select_model as _presentation_select_model,
    _select_saved_session,
)


def _select_model(argument: str = "") -> Optional[str]:
    """Compatibility wrapper preserving the historical patch seams."""
    return _presentation_select_model(
        argument,
        models_loader=get_available_models,
        model_filter=filter_models,
        offer_workspace_default=_offer_workspace_default,
    )


def _colorize_diff(diff: str) -> str:
    """Compatibility wrapper for confirmation diff formatting."""
    return colorize_diff(diff)


def _read_confirmation(prompt: str) -> Optional[str]:
    """Compatibility wrapper for the extracted confirmation reader."""
    return read_confirmation(prompt)


def _confirm_command(command: str) -> Tuple[bool, str]:
    """Compatibility wrapper for command confirmation."""
    return confirm_command(
        command,
        pause_voice_session=_pause_voice_session,
        drain_pending_input=_drain_pending_input,
    )


def _confirm_edit(result: Dict[str, Any]) -> Tuple[bool, str]:
    """Compatibility wrapper for edit confirmation."""
    return confirm_edit(
        result,
        pause_voice_session=_pause_voice_session,
        drain_pending_input=_drain_pending_input,
    )


def _pause_voice_session() -> None:
    """Compatibility wrapper for pausing the active voice session."""
    pause_voice_session()


def _visible_len(s: str) -> int:
    return visible_len(s)


def _rows_for_voice_line(line: str, width: Optional[int] = None) -> int:
    return rows_for_voice_line(line, width)


def _voice_loop(process: Callable[[str], None]) -> None:
    voice_loop(process, prompt=_prompt, drain_pending_input=_drain_pending_input)


def run(initial_request: str = "", reload: bool = False) -> None:
    """Compatibility wrapper for the extracted REPL implementation."""
    from harness.cli.repl import run_repl

    run_repl(initial_request, reload=reload)

def main() -> None:
    """Compatibility entry point for the packaged console script."""
    from harness.cli.main import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
