"""Raw terminal input, key handling, and interrupt support."""

import os
import select
import signal
import sys
import termios
import threading
import time
import tty
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional


class AgentInterrupted(Exception):
    """Raised when Escape asks the active agent turn to stop."""


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


