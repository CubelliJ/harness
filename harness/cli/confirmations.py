"""Interactive command and edit confirmation prompts."""

import os
import sys
import termios
import tty
from typing import Any, Callable, Dict, Optional, Tuple

from harness.cli.input import AgentInterrupted

PauseVoiceSession = Callable[[], None]
DrainPendingInput = Callable[[], None]


def colorize_diff(diff: str) -> str:
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


def read_confirmation(prompt: str) -> Optional[str]:
    """Read a confirmation line while allowing Escape to cancel immediately."""
    if not sys.stdin.isatty():
        return input(prompt).strip()
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        tty.setcbreak(fd)
        chars: list[bytes] = []
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
                return b"".join(chars).decode("utf-8", errors="replace").strip()
            if char in (b"\x7f", b"\x08"):
                if chars:
                    chars.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            chars.append(char)
            sys.stdout.write(char.decode("utf-8", errors="replace"))
            sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def confirm_command(
    command: str,
    *,
    pause_voice_session: PauseVoiceSession,
    drain_pending_input: DrainPendingInput,
) -> Tuple[bool, str]:
    """Require explicit human approval before running a shell command."""
    pause_voice_session()
    drain_pending_input()
    print("\n\033[33mProposed command:\033[0m %s" % command)
    try:
        answer = read_confirmation("Run this command? [Y/n] ")
    except (EOFError, KeyboardInterrupt):
        print()
        return False, ""
    if answer is None:
        return False, ""
    answer = answer.lower()
    if answer in {"", "y", "yes"}:
        return True, ""
    try:
        feedback = read_confirmation("Feedback (optional): ")
    except (EOFError, KeyboardInterrupt):
        print()
        feedback = ""
    return False, feedback or ""


def confirm_edit(
    result: Dict[str, Any],
    *,
    pause_voice_session: PauseVoiceSession,
    drain_pending_input: DrainPendingInput,
) -> Tuple[bool, str]:
    """Display a proposed diff and collect feedback when an edit is rejected."""
    pause_voice_session()
    drain_pending_input()
    print("\n\033[33mProposed edit: %s\033[0m" % result.get("path", ""))
    if result.get("diff"):
        diff = colorize_diff(result["diff"])
        print(diff, end="" if diff.endswith("\n") else "\n")
    try:
        answer = read_confirmation("Apply this edit? [Y/n] ")
    except (EOFError, KeyboardInterrupt):
        print()
        return False, ""
    if answer is None:
        return False, ""
    answer = answer.lower()
    if answer in {"", "y", "yes"}:
        return True, ""
    try:
        feedback = read_confirmation("Feedback (optional): ")
    except (EOFError, KeyboardInterrupt):
        print()
        feedback = ""
    return False, feedback or ""
