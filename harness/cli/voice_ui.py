"""Voice-mode terminal interaction and live transcript display."""

import os
import re
import select
import shutil
import sys
import termios
import tty
from typing import Callable, Optional

from harness.cli.input import _drain_pending_input
from harness.voice import VoiceSession, ensure_binary, is_supported, normalize_transcript

_voice_session: Optional[VoiceSession] = None
_voice_display_rows = 1
_ANSI_RE = re.compile(r"\033\[[0-9;]*[A-Za-z]")


def visible_len(s: str) -> int:
    return len(_ANSI_RE.sub("", s))


def terminal_width() -> int:
    try:
        return max(1, shutil.get_terminal_size(fallback=(80, 24)).columns)
    except OSError:
        return 80


def rows_for_voice_line(line: str, width: Optional[int] = None) -> int:
    """How many terminal rows `line` occupies when wrapped at `width`."""
    if width is None:
        width = terminal_width()
    vis = visible_len(line)
    if vis <= 0:
        return 1
    return max(1, (vis + width - 1) // width)


def clear_voice_display() -> None:
    """Erase the live transcript, including wrapped rows from a long hypothesis."""
    global _voice_display_rows
    if _voice_display_rows > 1:
        sys.stdout.write("\033[%dA" % (_voice_display_rows - 1))
    sys.stdout.write("\r\033[J")
    sys.stdout.flush()
    _voice_display_rows = 1


def render_voice_line(text: str, prompt: Callable[[], str]) -> None:
    global _voice_display_rows
    body = normalize_transcript(text) if text else "\033[90m[listening]\033[0m"
    line = prompt() + body
    clear_voice_display()
    sys.stdout.write(line)
    sys.stdout.flush()
    _voice_display_rows = rows_for_voice_line(line)


def wait_voice_keys(session: VoiceSession, prompt: Callable[[], str]) -> str:
    """Block until Enter, Escape, or Ctrl+C. Return submit, cancel, or interrupt."""
    pending = ""
    last_text: Optional[str] = None
    while True:
        crashed = session.unexpected_exit()
        if crashed:
            raise RuntimeError(crashed)
        text = session.current_text()
        if text != last_text:
            render_voice_line(text, prompt)
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


def pause_voice_session() -> None:
    """Stop the active microphone before a blocking confirmation prompt."""
    global _voice_session
    session = _voice_session
    if session is not None:
        session.stop()
        _voice_session = None


def voice_loop(
    process: Callable[[str], None],
    *,
    prompt: Callable[[], str],
    drain_pending_input: Callable[[], None] = _drain_pending_input,
) -> None:
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
            clear_voice_display()
            sys.stdout.write(prompt() + "\033[90m[starting]\033[0m")
            sys.stdout.flush()
            try:
                session.start()
                session.wait_ready()
            except (RuntimeError, OSError) as exc:
                clear_voice_display()
                print("\033[91m▸ voice: %s\033[0m" % exc)
                return

            tty.setcbreak(fd)
            try:
                action = wait_voice_keys(session, prompt)
            except KeyboardInterrupt:
                action = "interrupt"
            except RuntimeError as exc:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                clear_voice_display()
                print("\033[91m▸ voice: %s\033[0m" % exc)
                return
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

            text = session.stop()
            _voice_session = None
            if action == "cancel":
                clear_voice_display()
                print("\033[90m▸ voice mode off\033[0m")
                return
            if action == "interrupt":
                clear_voice_display()
                raise KeyboardInterrupt
            clear_voice_display()
            sys.stdout.write("%s%s\n" % (prompt(), normalize_transcript(text)))
            sys.stdout.flush()
            if not text.strip():
                continue
            drain_pending_input()
            try:
                process(text)
            except RuntimeError as exc:
                print("\033[91m▸ error: %s\033[0m" % exc)
    finally:
        if _voice_session is not None:
            _voice_session.stop()
            _voice_session = None
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

