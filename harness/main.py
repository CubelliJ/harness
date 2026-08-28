"""Main entry point and agent loop."""

import argparse
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
import threading
import signal
import time
from contextlib import contextmanager
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
    ASSISTANT_PREFIX,
    YOU_PROMPT,
    assistant_message,
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
from harness.llm import (
    execute_llm_call,
    filter_models,
    get_available_models,
    get_model_context_length,
    generate_conversation_title,
    parse_tool_call,
)
from harness.registry import (
    execute_tool,
    format_tool_result_content,
    get_full_system_prompt,
)
from harness.terminal import render_markdown
from harness.voice import VoiceSession, ensure_binary, is_supported, normalize_transcript

logger = logging.getLogger(__name__)

# Active STT helper, if any. Confirmations pause it so `input()` is not racing the mic.
_voice_session: Optional[VoiceSession] = None
# How many terminal rows the live transcript currently occupies.
_voice_display_rows = 1
_ANSI_RE = re.compile(r"\033\[[0-9;]*[A-Za-z]")

# Terminal bracketed-paste markers (enabled via CSI ?2004h).
_PASTE_START = "\u001b[200~"
_PASTE_END = "\u001b[201~"

# Terminals that support modified-key reporting use one of these encodings for
# Shift+Enter.  A plain CR cannot be distinguished from Enter, so terminals
# without modified-key reporting still need to be configured to emit one of
# these sequences (kitty keyboard protocol uses the first form).
_SHIFT_ENTER_SEQUENCES = (
    "\u001b[13;2u",       # kitty keyboard protocol
    "\u001b[27;2;13~",    # xterm modifyOtherKeys
    "\u001b[13;2~",       # older/alternate CSI encoding
)
# Ask capable terminals to report modified keys.  Unsupported terminals
# ignore this sequence, and the fallback encodings above remain accepted.
_KITTY_KEYBOARD_ENABLE = "\u001b[>1u"
_KITTY_KEYBOARD_DISABLE = "\u001b[<u"
# With the Kitty keyboard protocol enabled, Ctrl+C is reported as this CSI
# sequence rather than the traditional ETX byte (\\x03).
_CTRL_C_SEQUENCES = ("\u001b[99;5u",)


class AgentInterrupted(Exception):
    """Raised when Escape asks the active agent turn to stop."""


def _append_interrupted_tool_results(conversation: list[Dict[str, Any]]) -> None:
    """Close the latest tool-call turn when Escape abandons execution.

    OpenAI-compatible APIs reject a conversation containing an assistant tool
    call without a matching tool message.  A synthetic result lets the next
    user request continue safely instead of failing validation upstream.
    """
    assistant_index = None
    for index in range(len(conversation) - 1, -1, -1):
        message = conversation[index]
        if message.get("role") == "assistant" and message.get("tool_calls"):
            assistant_index = index
            break
    if assistant_index is None:
        return
    # Only repair a trailing, unfinished tool turn. A later user/assistant
    # message means this turn was already closed normally.
    trailing = conversation[assistant_index + 1:]
    if any(message.get("role") != "tool" for message in trailing):
        return
    calls = conversation[assistant_index].get("tool_calls") or []
    completed = {
        message.get("tool_call_id")
        for message in trailing
        if message.get("role") == "tool"
    }
    for index, call in enumerate(calls):
        call_id = call.get("id") if isinstance(call, dict) else None
        if not isinstance(call_id, str) or not call_id:
            call_id = f"interrupted-tool-{index}"
        if call_id not in completed:
            conversation.append(tool_message(
                call_id,
                json.dumps({"error": "interrupted by user; tool was not run"}),
            ))


@contextmanager
def _escape_interrupts() -> Iterator[threading.Event]:
    """Watch for Escape while an LLM request or tool is running.

    Escape is a byte, not a terminal signal. A small reader thread converts it
    to SIGUSR1 so the main thread can interrupt a blocking network or command
    call. The watcher is deliberately scoped to active work, so it cannot
    consume answers typed at confirmation prompts or the main REPL.
    """
    if not sys.stdin.isatty() or not hasattr(signal, "SIGUSR1"):
        yield threading.Event()
        return
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    stopped = threading.Event()
    interrupted = threading.Event()

    def handle_escape(_signum: int, _frame: Any) -> None:
        interrupted.set()
        raise AgentInterrupted

    def watch() -> None:
        while not stopped.is_set():
            ready, _, _ = select.select([fd], [], [], 0.05)
            if not ready:
                continue
            raw = os.read(fd, 1)
            if raw != b"\x1b":
                # In normal use no input is expected during active work.
                continue

            # Escape can arrive as the first byte of a kitty/xterm key
            # sequence (for example ESC [ 99 ; 5 u for Ctrl+C).  Do not
            # signal immediately and leave the tail queued for the next REPL
            # prompt: consume the complete sequence first.  A lone Escape is
            # still recognized after the short grace period.
            sequence = bytearray(raw)
            deadline = time.monotonic() + 0.05
            while time.monotonic() < deadline:
                remaining = max(0.0, deadline - time.monotonic())
                more, _, _ = select.select([fd], [], [], remaining)
                if not more:
                    break
                part = os.read(fd, 1)
                if not part:
                    break
                sequence.extend(part)
                if part in b"~uabcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ":
                    break
            interrupted.set()
            os.kill(os.getpid(), signal.SIGUSR1)
            return

    previous = signal.signal(signal.SIGUSR1, handle_escape)
    thread: Optional[threading.Thread] = None
    try:
        tty.setcbreak(fd)
        thread = threading.Thread(target=watch, daemon=True)
        thread.start()
        yield interrupted
    finally:
        stopped.set()
        if thread is not None:
            thread.join(timeout=0.2)
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        signal.signal(signal.SIGUSR1, previous)


def _interruptible_call(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run provider/tool work while watching the terminal for Escape."""
    with _escape_interrupts():
        return function(*args, **kwargs)


def _is_shift_enter(sequence: str) -> bool:
    return sequence in _SHIFT_ENTER_SEQUENCES


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


def _tool_status(name: str, summary: str) -> str:
    """Format a tool result as a small decorative status badge."""
    summary = str(summary)
    failed = summary.startswith(("error", "rejected")) or "_rejected" in summary
    icon = "!" if failed else "✓"
    color = "\033[91m" if failed else "\033[92m"
    return f"\033[90m   ├─ {color}{icon}\033[0m \033[96m{name}\033[0m \033[90m· {summary}\033[0m"


def _echo(ch: str) -> None:
    if ch == "\n":
        sys.stdout.write("\n")
    elif ch in ("\t",) or ch >= " ":
        sys.stdout.write(ch)
    sys.stdout.flush()


def _read_input(prompt: str) -> str:
    """Read one request; bracketed paste keeps newlines as part of the input."""
    if not sys.stdin.isatty():
        return input(prompt)

    sys.stdout.write(prompt)
    sys.stdout.flush()

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\u001b[?2004h" + _KITTY_KEYBOARD_ENABLE)
        sys.stdout.flush()

        buf: list[str] = []
        pending = ""
        in_paste = False

        while True:
            ch = sys.stdin.read(1)
            if not ch:
                raise EOFError
            if ch == "\u0003":
                raise KeyboardInterrupt

            pending += ch

            # The Kitty keyboard protocol encodes Ctrl+C as CSI 99;5u. Handle
            # it before generic escape-sequence filtering, which would drop it.
            if not in_paste and pending in _CTRL_C_SEQUENCES:
                raise KeyboardInterrupt

            # Shift+Enter is reported as an escape sequence by terminals that
            # support modified keys.  Treat it as an embedded newline rather
            # than the submit key.  This check must happen before the generic
            # escape-sequence handling below, which intentionally ignores
            # unknown escape sequences.
            if not in_paste and _is_shift_enter(pending):
                buf.append("\n")
                _echo("\n")
                pending = ""
                continue

            if not in_paste and _PASTE_START.startswith(pending):
                if pending == _PASTE_START:
                    pending = ""
                    in_paste = True
                continue

            if in_paste:
                if _PASTE_END.startswith(pending):
                    if pending == _PASTE_END:
                        pending = ""
                        in_paste = False
                    continue
                # Not an end-marker prefix — commit pending as paste content.
                for c in pending:
                    buf.append(c)
                    _echo(c)
                pending = ""
                continue

            # Incomplete ESC sequence (arrows, etc.): hold or drop.
            if pending == "\u001b" or (
                pending.startswith("\u001b[")
                and not pending.endswith("~")
                and not pending[-1].isalpha()
                and len(pending) < 16
            ):
                if _PASTE_START.startswith(pending):
                    continue
                if pending.startswith("\u001b[") and len(pending) < 16:
                    continue
                pending = ""
                continue
            if pending.startswith("\u001b"):
                pending = ""
                continue

            # In cbreak, Enter is typically \r (not \n).
            if pending in ("\r", "\n"):
                pending = ""
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(buf)

            if pending in ("\x7f", "\x08"):
                pending = ""
                if buf and buf[-1] != "\n":
                    buf.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                elif buf:
                    buf.pop()
                continue

            for c in pending:
                buf.append(c)
                _echo(c)
            pending = ""
    finally:
        sys.stdout.write("\u001b[?2004l" + _KITTY_KEYBOARD_DISABLE)
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


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


def _drain_pending_input() -> None:
    """Drop leftover keypresses so the next input() is not auto-answered.

    Voice mode reads Enter in cbreak as CR; many terminals also queue LF.
    That LF would otherwise complete a confirmation prompt unexpectedly.
    """
    if not sys.stdin.isatty():
        return
    fd = sys.stdin.fileno()
    try:
        termios.tcflush(fd, termios.TCIFLUSH)
    except termios.error:
        pass
    while True:
        ready, _, _ = select.select([fd], [], [], 0)
        if not ready:
            return
        chunk = os.read(fd, 4096)
        if not chunk:
            return


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
        _run_turn(user_input)

    def _run_turn(_user_input: str) -> None:
        nonlocal session_auto_approve, context_tokens
        compact()
        persist()
        while True:
            compact()
            content, tool_calls, usage = _interruptible_call(execute_llm_call, conversation)
            raw_prompt_tokens = usage.get("prompt_tokens")
            if isinstance(raw_prompt_tokens, int) and not isinstance(raw_prompt_tokens, bool):
                context_tokens = raw_prompt_tokens
            if not tool_calls:
                conversation.append(assistant_message(content, usage=usage))
                persist()
                maybe_generate_title()
                if content:
                    print(f"{ASSISTANT_PREFIX}{render_markdown(content)}")
                return
            if content:
                print(f"{ASSISTANT_PREFIX}{render_markdown(content)}")
            conversation.append(assistant_message(content or None, tool_calls=tool_calls, usage=usage))
            persist()
            for tc in tool_calls:
                # A malformed model response must become a tool error, not a
                # filesystem operation or a crashed session. Preserve the call
                # id when possible so the provider can continue the exchange.
                try:
                    call_id, name, args = parse_tool_call(tc)
                except ValueError as exc:
                    call_id = tc.get("id") if isinstance(tc, dict) else ""
                    call_id = call_id or "invalid-tool-call"
                    name = ((tc.get("function") or {}).get("name", "invalid")
                            if isinstance(tc, dict) and isinstance(tc.get("function"), dict)
                            else "invalid")
                    args = {}
                    result = {"error": str(exc)}
                else:
                    if name == "run_command":
                        approved, feedback = _confirm_command(args.get("command", ""))
                        if approved:
                            result = _interruptible_call(execute_tool, name, args)
                        else:
                            result = {"action": "command_rejected"}
                            if feedback:
                                result["feedback"] = feedback
                    elif name == "edit_file":
                        preview_args = dict(args, apply=False)
                        result = _interruptible_call(execute_tool, name, preview_args)
                        if not result.get("error") and result.get("action") != "old_str not found":
                            if config.dry_run():
                                result["action"] = "dry_run"
                            elif session_auto_approve:
                                result = _interruptible_call(execute_tool, name, dict(args, apply=True))
                            else:
                                approved, feedback = _confirm_edit(result)
                                if approved:
                                    result = _interruptible_call(execute_tool, name, dict(args, apply=True))
                                else:
                                    result["action"] = "edit_rejected"
                                    result.pop("diff", None)
                                    if feedback:
                                        result["feedback"] = feedback
                    else:
                        result = _interruptible_call(execute_tool, name, args)
                summary = (result.get("error") or result.get("action") or
                           result.get("path") or result.get("file_path") or "ok")
                print(_tool_status(name, summary))
                conversation.append(tool_message(call_id, format_tool_result_content(name, result)))
                if name == "read_image" and result.get("image_url") and not result.get("error"):
                    conversation.append(user_message(
                        f"Visual context loaded from {result.get('file_path', 'the image file')}.",
                        [{"type": "image_url", "image_url": {"url": result["image_url"]}}],
                    ))
                    conversation[-1]["image_context"] = True
            persist()

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


def main() -> None:
    # Configuration is a subcommand-like convenience kept compatible with the
    # existing argument parser. It is available before packaging as well.
    if len(sys.argv) > 1 and sys.argv[1] == "configure":
        config._try_load_dotenv()
        config.configure()
        return

    parser = argparse.ArgumentParser(description="CLI coding agent")
    parser.add_argument("--yes", action="store_true", help="approve all file edits")
    parser.add_argument("--dry-run", action="store_true", help="show edits without applying them")
    parser.add_argument(
        "--reload", action="store_true",
        help="resume the previous persisted conversation",
    )
    parser.add_argument(
        "--request", "-r", default="",
        help="run one request non-interactively, then exit",
    )
    parser.add_argument("--scenario", help="load the request from eval_scenarios/manifest.json")
    parser.add_argument(
        "--manifest", default=str(Path(__file__).resolve().parent.parent / "eval_scenarios" / "manifest.json"),
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if args.scenario and not args.request:
        try:
            manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
            scenario = manifest[args.scenario]
            args.request = scenario["task"]
            # A scenario is self-contained: use its workspace/history unless
            # the caller explicitly supplied either environment variable.
            os.environ.setdefault("HARNESS_WORKSPACE", scenario["workspace"])
            os.environ.setdefault(
                "HARNESS_HISTORY_FILE",
                str(Path(scenario["workspace"]) / "history.txt"),
            )
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            parser.error(f"could not load scenario {args.scenario!r}: {exc}")
    if args.yes:
        os.environ["HARNESS_AUTO_APPROVE"] = "1"
    if args.dry_run:
        os.environ["HARNESS_DRY_RUN"] = "1"
    config.init()
    request = args.request
    if not request and not sys.stdin.isatty():
        request = sys.stdin.read().strip()
    run(request, reload=args.reload)


if __name__ == "__main__":
    main()
