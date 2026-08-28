"""REPL session lifecycle and command dispatch.

This module temporarily consumes terminal helpers from ``harness.main``.
Those helpers will move into focused CLI modules in subsequent extractions.
"""

import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Optional

from harness import config
from harness.config import (
    CONTEXT_COMPACTION_CAP,
    CONTEXT_COMPACTION_RATIO,
    history_file_path,
)
from harness.conversation import (
    compact_conversation,
    conversation_cost,
    YOU_PROMPT,
    load_conversation_state,
    load_session_catalog,
    save_conversation_state,
    session_catalog_path,
    update_session_catalog,
    save_conversation_history,
    session_state_path,
    system_message,
    user_message,
)
from harness.registry import get_full_system_prompt
from harness.llm import (
    get_available_models,
    get_model_context_length,
    generate_conversation_title,
    filter_models,
)
from harness.voice import VoiceSession, ensure_binary, is_supported, normalize_transcript
from harness.cli.agent_loop import run_turn

logger = logging.getLogger(__name__)

from harness.main import (
    AgentInterrupted,
    _append_interrupted_tool_results,
    _confirm_command,
    _confirm_edit,
    _drain_pending_input,
    _format_tokens,
    _offer_workspace_default,
    _pause_voice_session,
    _print_context,
    _print_cost,
    _prompt,
    _read_input,
    _select_model,
    _select_saved_session,
    _voice_loop,
    _interruptible_call,
    _banner,
)

def run_repl(initial_request: str = "", reload: bool = False) -> None:
    """Run the REPL, optionally resuming the persisted conversation."""
    _banner()
    session_auto_approve = config.auto_approve()
    context_tokens: Optional[int] = None
    context_limit = get_model_context_length()
    workspace = config.workspace_root()
    history_path = history_file_path()
    state_path = session_state_path(history_path)
    catalog_path = session_catalog_path(state_path)
    saved_sessions = load_session_catalog(catalog_path, workspace)
    selected_path = None
    session_title: Optional[str] = None
    if reload:
        selected_path = _select_saved_session(saved_sessions)
        if selected_path is not None:
            state_path = selected_path
            history_path = selected_path.with_suffix(".txt")
            selected = next((s for s in saved_sessions if s.get("path") == str(selected_path)), None)
            session_title = selected.get("title") if selected else None
    conversation = load_conversation_state(state_path) if reload else None
    resumed = conversation is not None
    if conversation is not None:
        # Older interrupted sessions may contain an assistant tool call with
        # no result. Repair that state before the first resumed provider call.
        _append_interrupted_tool_results(conversation)
    if conversation is None:
        conversation = [system_message(get_full_system_prompt(config.workspace_root()))]
    title_generated = session_title is not None

    session_registered = resumed

    def persist(register: Optional[bool] = None) -> None:
        nonlocal session_registered
        save_conversation_history(history_path, conversation)
        save_conversation_state(state_path, conversation)
        if register is None:
            register = not session_registered
        if register:
            update_session_catalog(catalog_path, state_path, conversation, session_title, workspace)
            session_registered = True

    def maybe_generate_title() -> None:
        nonlocal session_title, title_generated
        if title_generated or not any(m.get("role") == "user" for m in conversation):
            return
        title_generated = True
        status = "\033[90m▸ generating conversation title...\033[0m"
        interactive = sys.stdout.isatty()
        if interactive:
            sys.stdout.write(status)
            sys.stdout.flush()
        else:
            print(status, flush=True)
        try:
            session_title = generate_conversation_title(conversation)
        except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("could not generate conversation title: %s", exc)
        finally:
            if interactive:
                sys.stdout.write("\r\033[2K")
                sys.stdout.flush()
        persist()

    # Write the active state for crash recovery, but do not list an empty session.
    persist(register=False)
    if resumed:
        print(f"\033[90m▸ resumed conversation ({len(conversation)} messages)\033[0m")

    def compaction_budget() -> Optional[int]:
        if not context_limit or context_limit < 1:
            return None
        return min(CONTEXT_COMPACTION_CAP, int(context_limit * CONTEXT_COMPACTION_RATIO))

    def compact(force: bool = False) -> bool:
        changed = compact_conversation(conversation, compaction_budget(), force=force)
        if changed:
            persist()
        return changed

    def clear_conversation() -> None:
        nonlocal history_path, state_path, session_title, title_generated, session_registered
        conversation[:] = [
            system_message(get_full_system_prompt(workspace)),
            system_message("[New conversation started. Treat the next request as a fresh task.]"),
        ]
        session_title = None
        title_generated = False
        session_registered = False
        state_path = state_path.with_name(
            f"{state_path.stem}_{uuid.uuid4().hex}.json"
        )
        history_path = state_path.with_suffix(".txt")
        persist(register=False)

    def process(user_input: str) -> None:
        nonlocal session_auto_approve, context_tokens
        conversation.append(user_message(user_input))
        interrupted = False
        try:
            _process_turn(user_input)
        except AgentInterrupted:
            interrupted = True
            # A stream may have already written a complete Markdown line.
            # Keep the interruption status on its own terminal line.
            print()
            _append_interrupted_tool_results(conversation)
            # Modified-key sequences can finish arriving after Escape has
            # already interrupted the active call. Never expose their tail to
            # the next request prompt.
            _drain_pending_input()
            print("\033[33m▸ interrupted — enter feedback or a new request\033[0m")
        finally:
            if interrupted:
                persist()

    def _process_turn(user_input: str) -> None:
        compact()
        persist()
        run_turn(
            conversation,
            session_auto_approve=session_auto_approve,
            compact=compact,
            persist=persist,
            maybe_generate_title=maybe_generate_title,
            confirm_command=_confirm_command,
            confirm_edit=_confirm_edit,
            interruptible_call=_interruptible_call,
            update_tokens=_update_context_tokens,
        )

    def _update_context_tokens(prompt_tokens: Optional[int]) -> None:
        nonlocal context_tokens
        context_tokens = prompt_tokens

    if initial_request:
        try:
            process(initial_request)
        except RuntimeError as e:
            print(f"\033[91m▸ error: {e}\033[0m")
        return

    while True:
        try:
            user_input = _read_input(_prompt())
        except (KeyboardInterrupt, EOFError):
            return
        command = user_input.strip().lower()
        if command in {"/quit", "/exit"}:
            return
        if command in {"/auto-accept", "/auto-approve"}:
            session_auto_approve = True
            print("\033[90m▸ auto-accept enabled for this session\033[0m")
            continue
        if command in {"/auto-accept off", "/auto-approve off"}:
            session_auto_approve = False
            print("\033[90m▸ auto-accept disabled for this session\033[0m")
            continue
        if command == "/context":
            _print_context(context_tokens, context_limit)
            continue
        if command in {"/cost", "/cost conversation"}:
            _print_cost(conversation)
            continue
        if command == "/cost last":
            _print_cost(conversation, last=True)
            continue
        if command == "/compact":
            if compact(force=True):
                print("\033[90m▸ context compacted\033[0m")
            else:
                print("\033[90m▸ no complete conversation turn available to compact\033[0m")
            continue
        if command == "/clear":
            clear_conversation()
            context_tokens = None
            print("\033[90m▸ new conversation started\033[0m")
            continue
        if command == "/model" or command.startswith("/model "):
            selected_model = _select_model(user_input.strip()[len("/model"):].strip())
            if selected_model:
                context_tokens = None
                context_limit = get_model_context_length()
                print(f"\033[90m▸ context limit refreshed: {_format_tokens(context_limit)} tokens\033[0m")
            continue
        if command == "/voice":
            try:
                _voice_loop(process)
            except KeyboardInterrupt:
                return
            continue
        if command == "/voice off":
            print("\033[90m▸ voice mode is off\033[0m")
            continue
        if command in {"/help", "?"}:
            print("Commands: /model, /model <number|id|search>, /context, /cost, /cost last, /compact, /clear, /auto-accept, /auto-accept off, /voice, /quit")
            continue
        if user_input.strip():
            try:
                process(user_input)
            except RuntimeError as e:
                print(f"\033[91m▸ error: {e}\033[0m")

