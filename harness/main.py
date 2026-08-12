"""Main entry point and agent loop."""

import logging
import sys
import termios
import tty

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


def run() -> None:
    _banner()
    history_path = history_file_path()
    conversation = [system_message(get_full_system_prompt())]
    save_conversation_history(history_path, conversation)

    while True:
        try:
            user_input = _read_input(YOU_PROMPT)
        except (KeyboardInterrupt, EOFError):
            break

        conversation.append(user_message(user_input))
        save_conversation_history(history_path, conversation)

        while True:
            content, tool_calls = execute_llm_call(conversation)

            if not tool_calls:
                conversation.append(assistant_message(content))
                save_conversation_history(history_path, conversation)
                if content:
                    print(f"{ASSISTANT_PREFIX}{content}")
                break

            if content:
                print(f"{ASSISTANT_PREFIX}{content}")

            conversation.append(assistant_message(content or None, tool_calls=tool_calls))
            save_conversation_history(history_path, conversation)

            for tc in tool_calls:
                call_id, name, args = parse_tool_call(tc)
                result = execute_tool(name, args)
                summary = (
                    result.get("error")
                    or result.get("action")
                    or result.get("path")
                    or result.get("file_path")
                    or "ok"
                )
                print(f"\u001b[90m▸ tool {name} → {summary}\u001b[0m")
                conversation.append(
                    tool_message(call_id, format_tool_result_content(name, result))
                )
            save_conversation_history(history_path, conversation)


def main() -> None:
    config.init()
    run()


if __name__ == "__main__":
    main()
