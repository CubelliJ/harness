"""Main entry point and agent loop."""

import logging
import os
import re
import select
import shutil
import subprocess
import sys
import termios
import tty
import uuid
import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

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
from harness.llm import (
    filter_models,
    get_available_models,
    get_model_context_length,
    generate_conversation_title,
)
from harness.registry import get_full_system_prompt
from harness.terminal import render_markdown
from harness.voice import VoiceSession, ensure_binary, is_supported, normalize_transcript

logger = logging.getLogger(__name__)

# Active STT helper, if any. Confirmations pause it so `input()` is not racing the mic.
_voice_session: Optional[VoiceSession] = None
# How many terminal rows the live transcript currently occupies.
_voice_display_rows = 1
_ANSI_RE = re.compile(r"\033\[[0-9;]*[A-Za-z]")


def _format_tokens(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "?"


def _context_bar(prompt_tokens: Optional[int], context_limit: Optional[int], width: int = 30) -> str:
    if prompt_tokens is None:
        return "[unknown]"
    if not context_limit or context_limit < 1:
        return f"[{prompt_tokens:,} tokens; limit unknown]"
    ratio = min(1.0, max(0.0, prompt_tokens / context_limit))
    filled = int(round(ratio * width))
    return "[%s%s] %d%%" % ("#" * filled, "." * (width - filled), round(ratio * 100))


def _print_context(prompt_tokens: Optional[int], context_limit: Optional[int]) -> None:
    usage = _format_tokens(prompt_tokens)
    limit = _format_tokens(context_limit) if context_limit else "unknown"
    bar = _context_bar(prompt_tokens, context_limit)
    # Keep the helper plain for scripts/tests while making the interactive
    # status line a little more luminous.
    print(f"\033[90m▸ context {usage} / {limit} tokens \033[36m{bar}\033[0m")


def _print_cost(conversation: list[Dict[str, Any]], last: bool = False) -> None:
    summary = conversation_cost(conversation)
    if not summary["calls"]:
        print("\033[90m▸ no provider usage recorded yet\033[0m")
        return
    if last:
        usage = summary["last_usage"] or {}
        details = usage.get("prompt_tokens_details")
        cached = details.get("cached_tokens") if isinstance(details, dict) else None
        cost = usage.get("cost")
        try:
            cost_text = f"${float(cost):.6f}" if cost is not None else "unknown"
        except (TypeError, ValueError):
            cost_text = "unknown"
        print(f"\033[90m▸ last call: {cost_text} · {_format_tokens(usage.get('prompt_tokens'))} in / "
              f"{_format_tokens(usage.get('completion_tokens'))} out · "
              f"{_format_tokens(cached)} cached\033[0m")
        return
    cost = summary["cost"]
    cost_text = f"${cost:.6f}" if cost is not None else "unknown"
    print(f"\033[90m▸ conversation: {cost_text} · {summary['calls']} calls · "
          f"{_format_tokens(summary['prompt_tokens'])} in / "
          f"{_format_tokens(summary['completion_tokens'])} out · "
          f"{_format_tokens(summary['cached_input_tokens'])} cached\033[0m")


def _format_model_context(model: Dict[str, Any]) -> str:
    context = model.get("context_length")
    return f"{int(context):,}" if context is not None else "?"


def _git_branch() -> str:
    """Return the current branch for the workspace, or a friendly fallback."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=config.workspace_root(),
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "no-git"
    branch = result.stdout.strip()
    if branch:
        return branch
    return "detached" if result.returncode == 0 else "no-git"


def _prompt() -> str:
    """Build the prompt with a fresh branch badge for every interaction."""
    return f"{YOU_PROMPT}\033[35m⎇ {_git_branch()}\033[0m  "


def _select_saved_session(sessions: list[Dict[str, Any]]) -> Optional[Path]:
    """Prompt for one of the recent saved sessions; choose newest on non-TTY input."""
    if not sessions:
        return None
    print("\033[36mRecent conversations:\033[0m")
    for index, session in enumerate(sessions[:5], 1):
        title = session.get("title") or "Untitled conversation"
        updated = session.get("updated", "")
        print(f"  {index}. {title} \033[90m{updated}\033[0m")
    if not sys.stdin.isatty():
        return Path(sessions[0]["path"])
    count = min(5, len(sessions))
    choice_label = "1" if count == 1 else f"1-{count}"
    try:
        answer = input(f"Resume [{choice_label}, Enter to cancel]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if not answer:
        return None
    try:
        index = int(answer)
    except ValueError:
        print("\033[90m▸ enter a conversation number\033[0m")
        return None
    if not 1 <= index <= min(5, len(sessions)):
        print("\033[90m▸ no conversation with that number\033[0m")
        return None
    return Path(sessions[index - 1]["path"])


def _select_model(argument: str = "") -> Optional[str]:
    """List models, filter by search text, or select one by number/id.

    ``/model`` lists everything, ``/model open`` lists models matching "open",
    ``/model open 2`` picks the second match, and a bare number or exact
    provider/model-id still selects from the full catalogue.
    """
    try:
        models = get_available_models()
    except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"\033[91m\u25b8 model catalogue unavailable: {exc}\033[0m")
        return None
    if not models:
        print("\033[90m\u25b8 OpenRouter returned no models\033[0m")
        return None
    query = argument.strip()

    def _switch(model: Dict[str, Any]) -> str:
        config.set_model(model["id"])
        print(f"\033[90m\u25b8 model switched to {model['id']}\033[0m")
        _offer_workspace_default(model["id"])
        return model["id"]

    if query.isdigit():
        if 1 <= int(query) <= len(models):
            return _switch(models[int(query) - 1])
        print(f"\033[90m\u25b8 enter a model number 1-{len(models)} or an exact model id\033[0m")
        return None
    if query:
        exact = next((m for m in models if m["id"].lower() == query.lower()), None)
        if exact is not None:
            return _switch(exact)

    filter_text = query
    pick = None
    parts = query.split()
    if len(parts) > 1 and parts[-1].isdigit():
        filter_text = " ".join(parts[:-1])
        pick = int(parts[-1])
    if filter_text:
        models = filter_models(models, filter_text)
        if not models:
            print(f"\033[90m\u25b8 no models matching {filter_text!r}\033[0m")
            return None
    if pick is not None:
        if 1 <= pick <= len(models):
            return _switch(models[pick - 1])
        print(f"\033[90m\u25b8 choose a model number 1-{len(models)} from /model {filter_text}\033[0m")
        return None

    print("\033[36mAvailable OpenRouter models:\033[0m")
    for index, model in enumerate(models, 1):
        name = model.get("name") or model["id"]
        print(f"  {index:>3}. {name}  \033[90m{model['id']} \u00b7 {_format_model_context(model)} tokens\033[0m")
    saved_default = config.workspace_model()
    if saved_default:
        print(f"\033[90mWorkspace default: {saved_default}\033[0m")
    if query:
        print(f"\033[90m{len(models)} matching models for {filter_text!r}; pick with /model {filter_text} <number>\033[0m")
    else:
        print("\033[90mUse /model <number>, /model <provider/model-id>, or /model <search text>\033[0m")
    return None


def _offer_workspace_default(model_id: str) -> None:
    """Offer to persist a freshly selected model as this workspace's default."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return
    if config.workspace_model() == model_id:
        return
    try:
        answer = input(
            f"Save {model_id} as the default model for this workspace? [y/N]: "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if answer not in {"y", "yes"}:
        print("\033[90m▸ keeping the session-only model\033[0m")
        return
    try:
        path = config.save_workspace_model(model_id)
    except OSError as exc:
        print(f"\033[91m▸ could not save workspace default: {exc}\033[0m")
        return
    print(f"\033[90m▸ saved as workspace default in {path}\033[0m")


def _banner() -> None:
    """Show a compact, decorative welcome dashboard before the REPL starts."""
    cyan = "\u001b[36m"
    dim = "\u001b[90m"
    white = "\u001b[97m"
    reset = "\u001b[0m"
    title = f"◈  H A R N E S S   {get_version()}"
    model = config.get_model()
    workspace = str(config.workspace_root())
    print(
        f"\n{cyan}\u001b[1m   ╭────────────────────────────────────────────╮{reset}\n"
        f"{cyan}\u001b[1m   │{title.center(44)}│{reset}\n"
        f"{cyan}\u001b[1m   ╰────────────────────────────────────────────╯{reset}\n"
        f"{dim}   ◌ model      {white}{model}{reset}\n"
        f"{dim}   ◌ workspace  {white}{workspace}{reset}\n"
        f"{dim}   ◌ branch     {white}⎇ {_git_branch()}{reset}\n"
        f"{dim}   ────────────────────────────────────────────{reset}\n"
        f"{cyan}   ◆ ready{reset}  {dim}Type a request · Escape interrupts · /help for shortcuts{reset}\n"
    )


def _colorize_diff(diff: str) -> str:
    """Add background colors to added and removed diff lines."""
    green = "\033[30;42m"
    red = "\033[30;41m"
    reset = "\033[0m"
    colored = []
    for line in diff.splitlines(keepends=True):
        # Do not color the unified-diff file headers ("+++" and "---").
        if line.startswith("+") and not line.startswith("+++"):
            colored.append(f"{green}{line}{reset}")
        elif line.startswith("-") and not line.startswith("---"):
            colored.append(f"{red}{line}{reset}")
        else:
            colored.append(line)
    return "".join(colored)


def _pause_voice_session() -> None:
    """Stop the mic before blocking on keyboard confirmations."""
    global _voice_session
    session = _voice_session
    if session is not None:
        session.stop()
        _voice_session = None


def _read_confirmation(prompt: str) -> Optional[str]:
    """Read a confirmation line while allowing Escape to cancel immediately."""
    if not sys.stdin.isatty():
        return input(prompt).strip()
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        tty.setcbreak(fd)
        chars: list[str] = []
        while True:
            char = os.read(fd, 1)
            if not char:
                raise EOFError
            if char == b"\x1b":
                sys.stdout.write("\n")
                sys.stdout.flush()
                raise AgentInterrupted
            if char in (b"\r", b"\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                return bytes(chars).decode("utf-8", errors="replace").strip()
            if char in (b"\x7f", b"\x08"):
                if chars:
                    chars.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            chars.append(char[0])
            sys.stdout.write(char.decode("utf-8", errors="replace"))
            sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _confirm_command(command: str) -> Tuple[bool, str]:
    """Require an explicit human approval before running a shell command."""
    _pause_voice_session()
    _drain_pending_input()
    print("\n\033[33mProposed command:\033[0m %s" % command)
    try:
        answer = _read_confirmation("Run this command? [Y/n] ")
    except (EOFError, KeyboardInterrupt):
        print()
        return False, ""
    if answer is None:
        return False, ""
    answer = answer.lower()
    if answer in {"", "y", "yes"}:
        return True, ""
    try:
        feedback = _read_confirmation("Feedback (optional): ")
    except (EOFError, KeyboardInterrupt):
        print()
        feedback = ""
    return False, feedback or ""


def _confirm_edit(result: Dict[str, Any]) -> Tuple[bool, str]:
    """Display a proposed diff and collect feedback when an edit is rejected."""
    _pause_voice_session()
    _drain_pending_input()
    print("\n\033[33mProposed edit: %s\033[0m" % result.get("path", ""))
    if result.get("diff"):
        diff = _colorize_diff(result["diff"])
        print(diff, end="" if diff.endswith("\n") else "\n")
    try:
        answer = _read_confirmation("Apply this edit? [Y/n] ")
    except (EOFError, KeyboardInterrupt):
        print()
        return False, ""
    if answer is None:
        return False, ""
    answer = answer.lower()
    if answer in {"", "y", "yes"}:
        return True, ""
    try:
        feedback = _read_confirmation("Feedback (optional): ")
    except (EOFError, KeyboardInterrupt):
        print()
        feedback = ""
    return False, feedback or ""


def _visible_len(s: str) -> int:
    return len(_ANSI_RE.sub("", s))


def _terminal_width() -> int:
    try:
        return max(1, shutil.get_terminal_size(fallback=(80, 24)).columns)
    except OSError:
        return 80


def _rows_for_voice_line(line: str, width: Optional[int] = None) -> int:
    """How many terminal rows `line` occupies when wrapped at `width`."""
    if width is None:
        width = _terminal_width()
    vis = _visible_len(line)
    if vis <= 0:
        return 1
    return max(1, (vis + width - 1) // width)


def _clear_voice_display() -> None:
    """Erase the live transcript, including wrapped rows from a long hypothesis."""
    global _voice_display_rows
    if _voice_display_rows > 1:
        sys.stdout.write("\033[%dA" % (_voice_display_rows - 1))
    sys.stdout.write("\r\033[J")
    sys.stdout.flush()
    _voice_display_rows = 1


def _render_voice_line(text: str) -> None:
    global _voice_display_rows
    body = normalize_transcript(text) if text else "\033[90m[listening]\033[0m"
    line = _prompt() + body
    _clear_voice_display()
    sys.stdout.write(line)
    sys.stdout.flush()
    _voice_display_rows = _rows_for_voice_line(line)


def _wait_voice_keys(session: VoiceSession) -> str:
    """Block until Enter, Escape, or Ctrl+C. Return submit, cancel, or interrupt."""
    pending = ""
    last_text: Optional[str] = None
    while True:
        crashed = session.unexpected_exit()
        if crashed:
            raise RuntimeError(crashed)
        text = session.current_text()
        if text != last_text:
            _render_voice_line(text)
            last_text = text
        ready, _, _ = select.select([sys.stdin], [], [], 0.05)
        if not ready:
            continue
        raw = os.read(sys.stdin.fileno(), 1)
        if not raw:
            return "interrupt"
        ch = raw.decode("latin-1")
        if ch == "\x03":
            return "interrupt"
        pending += ch
        if pending in ("\r", "\n"):
            extra, _, _ = select.select([sys.stdin], [], [], 0)
            if extra:
                nxt = os.read(sys.stdin.fileno(), 1)
                if nxt not in (b"\n", b"\r", b""):
                    pass
            return "submit"
        if pending == "\x1b":
            more, _, _ = select.select([sys.stdin], [], [], 0.05)
            if not more:
                return "cancel"
            pending += os.read(sys.stdin.fileno(), 1).decode("latin-1")
            if pending == "\x1b[":
                while True:
                    rest, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if not rest:
                        break
                    end = os.read(sys.stdin.fileno(), 1).decode("latin-1")
                    if end.isalpha() or end == "~":
                        break
                pending = ""
                continue
            return "cancel"
        pending = ""


def _voice_loop(process: Callable[[str], None]) -> None:
    """Sticky voice mode: listen, Enter submits, Escape returns to the typed REPL."""
    global _voice_session
    if not sys.stdin.isatty():
        print("\033[90m▸ voice mode needs an interactive terminal\033[0m")
        return
    if not is_supported():
        print("\033[90m▸ voice mode is only available on macOS\033[0m")
        return
    try:
        ensure_binary()
    except RuntimeError as exc:
        print("\033[91m▸ voice: %s\033[0m" % exc)
        return

    print("\033[90m▸ voice mode on — Enter submits, Escape exits\033[0m")
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        while True:
            session = VoiceSession()
            _voice_session = session
            _clear_voice_display()
            sys.stdout.write(_prompt() + "\033[90m[starting]\033[0m")
            sys.stdout.flush()
            try:
                session.start()
                session.wait_ready()
            except (RuntimeError, OSError) as exc:
                _clear_voice_display()
                print("\033[91m▸ voice: %s\033[0m" % exc)
                return

            tty.setcbreak(fd)
            try:
                action = _wait_voice_keys(session)
            except KeyboardInterrupt:
                action = "interrupt"
            except RuntimeError as exc:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                _clear_voice_display()
                print("\033[91m▸ voice: %s\033[0m" % exc)
                return
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

            text = session.stop()
            _voice_session = None
            if action == "cancel":
                _clear_voice_display()
                print("\033[90m▸ voice mode off\033[0m")
                return
            if action == "interrupt":
                _clear_voice_display()
                raise KeyboardInterrupt
            _clear_voice_display()
            sys.stdout.write("%s%s\n" % (_prompt(), normalize_transcript(text)))
            sys.stdout.flush()
            if not text.strip():
                continue
            _drain_pending_input()
            try:
                process(text)
            except RuntimeError as exc:
                print("\033[91m▸ error: %s\033[0m" % exc)
    finally:
        if _voice_session is not None:
            _voice_session.stop()
            _voice_session = None
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


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
