"""Main entry point and agent loop."""

import argparse
import logging
import os
import sys
import termios
import tty
import json
from pathlib import Path
from typing import Any, Dict, Tuple

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
from harness.llm import execute_llm_call, parse_tool_call
from harness.registry import (
    execute_tool,
    format_tool_result_content,
    get_full_system_prompt,
)
from harness.terminal import render_markdown

logger = logging.getLogger(__name__)

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


def _banner() -> None:
    print(
        f"\n\u001b[36m\u001b[1m"
        f"Harness v{get_version()}  |  {config.get_model()}  |  {config.workspace_root()}"
        f"\u001b[0m\n"
        "Type a request. Ctrl+C to exit.\n"
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


def _confirm_command(command: str) -> Tuple[bool, str]:
    """Require an explicit human approval before running a shell command."""
    print("\n\033[33mProposed command:\033[0m %s" % command)
    try:
        answer = input("Run this command? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False, ""
    if answer in {"y", "yes"}:
        return True, ""
    try:
        feedback = input("Feedback (optional): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        feedback = ""
    return False, feedback


def _confirm_edit(result: Dict[str, Any]) -> Tuple[bool, str]:
    """Display a proposed diff and collect feedback when an edit is rejected."""
    print("\n\033[33mProposed edit: %s\033[0m" % result.get("path", ""))
    if result.get("diff"):
        diff = _colorize_diff(result["diff"])
        print(diff, end="" if diff.endswith("\n") else "\n")
    try:
        answer = input("Apply this edit? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False, ""
    if answer in {"y", "yes"}:
        return True, ""
    try:
        feedback = input("Feedback (optional): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        feedback = ""
    return False, feedback


def run(initial_request: str = "") -> None:
    """Run the REPL, or process one request when initial_request is supplied."""
    _banner()
    session_auto_approve = config.auto_approve()
    history_path = history_file_path()
    conversation = [system_message(get_full_system_prompt())]
    save_conversation_history(history_path, conversation)

    def process(user_input: str) -> None:
        nonlocal session_auto_approve
        conversation.append(user_message(user_input))
        save_conversation_history(history_path, conversation)
        while True:
            content, tool_calls = execute_llm_call(conversation)
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
        if command in {"/help", "?"}:
            print("Commands: /auto-accept, /auto-accept off, /quit")
            continue
        if user_input.strip():
            try:
                process(user_input)
            except RuntimeError as e:
                print(f"\033[91m▸ error: {e}\033[0m")


def main() -> None:
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
