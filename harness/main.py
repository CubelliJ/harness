"""Main entry point and agent loop."""

import argparse
import logging
import os
import re
import select
import shutil
import sys
import termios
import tty
import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from harness import config, get_version
from harness.config import history_file_path
from harness.conversation import (
    ASSISTANT_PREFIX,
    YOU_PROMPT,
    assistant_message,
    save_conversation_history,
    system_message,
    tool_message,
    user_message,
)
from harness.llm import (
    execute_llm_call,
    get_available_models,
    get_model_context_length,
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
    print(f"\033[90m▸ context {usage} / {limit} tokens {_context_bar(prompt_tokens, context_limit)}\033[0m")


def _format_model_context(model: Dict[str, Any]) -> str:
    context = model.get("context_length")
    return f"{int(context):,}" if context is not None else "?"


def _select_model(argument: str = "") -> Optional[str]:
    """List models or select one by number/id for the current session."""
    try:
        models = get_available_models()
    except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"\033[91m▸ model catalogue unavailable: {exc}\033[0m")
        return None
    if not models:
        print("\033[90m▸ OpenRouter returned no models\033[0m")
        return None
    if argument:
        selected = None
        if argument.isdigit() and 1 <= int(argument) <= len(models):
            selected = models[int(argument) - 1]
        else:
            selected = next((m for m in models if m["id"].lower() == argument.lower()), None)
        if selected is None:
            print("\033[90m▸ enter a model number or exact model id from /model\033[0m")
            return None
        config.set_model(selected["id"])
        print(f"\033[90m▸ model switched to {selected['id']}\033[0m")
        return selected["id"]

    print("\033[36mAvailable OpenRouter models:\033[0m")
    for index, model in enumerate(models, 1):
        name = model.get("name") or model["id"]
        print(f"  {index:>3}. {name}  \033[90m{model['id']} · {_format_model_context(model)} tokens\033[0m")
    print("\033[90mUse /model <number> or /model <provider/model-id>\033[0m")
    return None


def _banner() -> None:
    print(
        f"\n\u001b[36m\u001b[1m"
        f"Harness v{get_version()}  |  {config.get_model()}  |  {config.workspace_root()}"
        f"\u001b[0m\n"
        "Type a request. /voice for speech input. Ctrl+C to exit.\n"
    )


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


def _confirm_command(command: str) -> Tuple[bool, str]:
    """Require an explicit human approval before running a shell command."""
    _pause_voice_session()
    _drain_pending_input()
    print("\n\033[33mProposed command:\033[0m %s" % command)
    try:
        answer = input("Run this command? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False, ""
    if answer in {"", "y", "yes"}:
        return True, ""
    try:
        feedback = input("Feedback (optional): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        feedback = ""
    return False, feedback


def _confirm_edit(result: Dict[str, Any]) -> Tuple[bool, str]:
    """Display a proposed diff and collect feedback when an edit is rejected."""
    _pause_voice_session()
    _drain_pending_input()
    print("\n\033[33mProposed edit: %s\033[0m" % result.get("path", ""))
    if result.get("diff"):
        diff = _colorize_diff(result["diff"])
        print(diff, end="" if diff.endswith("\n") else "\n")
    try:
        answer = input("Apply this edit? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False, ""
    if answer in {"", "y", "yes"}:
        return True, ""
    try:
        feedback = input("Feedback (optional): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        feedback = ""
    return False, feedback


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
    line = YOU_PROMPT + body
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
            sys.stdout.write(YOU_PROMPT + "\033[90m[starting]\033[0m")
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
            sys.stdout.write("%s%s\n" % (YOU_PROMPT, normalize_transcript(text)))
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


def run(initial_request: str = "") -> None:
    """Run the REPL, or process one request when initial_request is supplied."""
    _banner()
    session_auto_approve = config.auto_approve()
    context_tokens: Optional[int] = None
    context_limit = get_model_context_length()
    history_path = history_file_path()
    conversation = [system_message(get_full_system_prompt(config.workspace_root()))]
    save_conversation_history(history_path, conversation)

    def process(user_input: str) -> None:
        nonlocal session_auto_approve, context_tokens
        conversation.append(user_message(user_input))
        save_conversation_history(history_path, conversation)
        while True:
            content, tool_calls, usage = execute_llm_call(conversation)
            raw_prompt_tokens = usage.get("prompt_tokens")
            if isinstance(raw_prompt_tokens, int) and not isinstance(raw_prompt_tokens, bool):
                context_tokens = raw_prompt_tokens
            if not tool_calls:
                conversation.append(assistant_message(content))
                save_conversation_history(history_path, conversation)
                if content:
                    print(f"{ASSISTANT_PREFIX}{render_markdown(content)}")
                return
            if content:
                print(f"{ASSISTANT_PREFIX}{render_markdown(content)}")
            conversation.append(assistant_message(content or None, tool_calls=tool_calls))
            save_conversation_history(history_path, conversation)
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
                            result = execute_tool(name, args)
                        else:
                            result = {"action": "command_rejected"}
                            if feedback:
                                result["feedback"] = feedback
                    elif name == "edit_file":
                        preview_args = dict(args, apply=False)
                        result = execute_tool(name, preview_args)
                        if not result.get("error") and result.get("action") != "old_str not found":
                            if config.dry_run():
                                result["action"] = "dry_run"
                            elif session_auto_approve:
                                result = execute_tool(name, dict(args, apply=True))
                            else:
                                approved, feedback = _confirm_edit(result)
                                if approved:
                                    result = execute_tool(name, dict(args, apply=True))
                                else:
                                    result["action"] = "edit_rejected"
                                    result.pop("diff", None)
                                    if feedback:
                                        result["feedback"] = feedback
                    else:
                        result = execute_tool(name, args)
                summary = (result.get("error") or result.get("action") or
                           result.get("path") or result.get("file_path") or "ok")
                print(f"\u001b[90m▸ tool {name} → {summary}\u001b[0m")
                conversation.append(tool_message(call_id, format_tool_result_content(name, result)))
            save_conversation_history(history_path, conversation)

    if initial_request:
        try:
            process(initial_request)
        except RuntimeError as e:
            print(f"\033[91m▸ error: {e}\033[0m")
        return

    while True:
        try:
            user_input = _read_input(YOU_PROMPT)
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
            print("Commands: /model, /model <number|id>, /context, /auto-accept, /auto-accept off, /voice, /quit")
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
    run(request)


if __name__ == "__main__":
    main()
