"""macOS speech-to-text helper for /voice mode."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Keep the Swift sources inside the Python package so wheel installs retain
# the files needed to build the helper on first use.
_SOURCE_DIR = Path(__file__).resolve().parent / "native" / "stt"
_APP_NAME = "harness-stt.app"
_EXECUTABLE_NAME = "harness-stt"
_SOL_LOCAL = 0
_LOCAL_PEERPID = 2


def is_supported() -> bool:
    return sys.platform == "darwin"


def source_dir() -> Path:
    return _SOURCE_DIR


def binary_path() -> Path:
    override = os.environ.get("HARNESS_STT_BIN", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".harness" / "bin" / _APP_NAME


def app_executable(app: Path) -> Path:
    return app / "Contents" / "MacOS" / _EXECUTABLE_NAME


def _artifact_mtime(dest: Path) -> Optional[float]:
    if dest.suffix == ".app":
        exe = app_executable(dest)
        if exe.is_file():
            return exe.stat().st_mtime
        return None
    if dest.is_file():
        return dest.stat().st_mtime
    return None


def _needs_build(dest: Path) -> bool:
    dest_mtime = _artifact_mtime(dest)
    if dest_mtime is None:
        return True
    for name in ("main.swift", "Info.plist", "build.sh"):
        src = _SOURCE_DIR / name
        if src.is_file() and dest_mtime < src.stat().st_mtime:
            return True
    return False


def ensure_binary() -> Path:
    """Build the native STT helper if missing or stale. macOS only."""
    if not is_supported():
        raise RuntimeError("voice mode is only available on macOS")
    swift = _SOURCE_DIR / "main.swift"
    script = _SOURCE_DIR / "build.sh"
    if not swift.is_file() or not script.is_file():
        raise RuntimeError("STT sources missing under %s" % _SOURCE_DIR)
    dest = binary_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not _needs_build(dest):
        return dest
    if shutil.which("swiftc") is None:
        raise RuntimeError(
            "swiftc not found. Install Xcode Command Line Tools: xcode-select --install"
        )
    logger.info("building harness-stt -> %s", dest)
    proc = subprocess.run(
        ["bash", str(script), str(dest)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or "unknown build error"
        raise RuntimeError("failed to build harness-stt: %s" % detail)
    return dest


def normalize_transcript(text: str) -> str:
    """Collapse newlines and other whitespace so utterances stay one line."""
    return " ".join(str(text).split())


def _transcript_tokens(text: str) -> List[str]:
    """Return punctuation-insensitive words for replay comparisons."""
    return re.findall(r"\w+", text.casefold())


def _strip_replayed_prefix(previous: str, text: str) -> str:
    """Remove a finalized prefix replayed by a new recognition task."""
    old_tokens = _transcript_tokens(previous)
    new_tokens = _transcript_tokens(text)
    if not old_tokens or len(new_tokens) < len(old_tokens):
        return text
    if new_tokens[: len(old_tokens)] != old_tokens:
        return text
    return _drop_transcript_tokens(text, len(old_tokens))


def _drop_transcript_tokens(text: str, count: int) -> str:
    """Drop `count` leading words and punctuation from a transcript."""
    tokens = list(re.finditer(r"\w+", text, re.UNICODE))
    if not tokens or count > len(tokens):
        return text
    end = tokens[count - 1].end()
    suffix = re.match(r"\W*", text[end:], re.UNICODE)
    return text[end + (suffix.end() if suffix else 0) :]


def _strip_replayed_overlap(previous: str, text: str) -> str:
    """Remove a repeated tail of `previous` from a new task's hypothesis.

    A restarted Apple task does not always replay the entire finalized text;
    it may replay only the last few words (for example, ``world again``).
    """
    old_tokens = _transcript_tokens(previous)
    new_tokens = _transcript_tokens(text)
    limit = min(len(old_tokens), len(new_tokens))
    for count in range(limit, 0, -1):
        if old_tokens[-count:] == new_tokens[:count]:
            return _drop_transcript_tokens(text, count)
    return text


def _strip_replayed_leading_overlap(previous: str, text: str) -> str:
    """Remove a repeated beginning when a restarted task revises the tail.

    For example, a task may finalize ``Hello world one`` and restart with
    ``Hello world, 123 ...``. The first two words are replayed, but the new
    hypothesis is not a prefix of the finalized text.
    """
    old_tokens = _transcript_tokens(previous)
    new_tokens = _transcript_tokens(text)
    count = 0
    for old, new in zip(old_tokens, new_tokens):
        if old != new:
            break
        count += 1
    if count < 2:
        return text
    return _drop_transcript_tokens(text, count)


def _is_same_utterance(old: str, new: str) -> bool:
    """True when `new` revises `old` rather than starting a fresh phrase."""
    if not old or not new:
        return True
    if new.startswith(old):
        return True
    # Recognizers often drop a trailing word while revising. A much shorter
    # string is a new utterance (e.g. "the word is chicken" then "what").
    old_words = old.split()
    new_words = new.split()
    if old.startswith(new) and len(new_words) >= max(1, len(old_words) - 2):
        return True
    common = 0
    for left, right in zip(old_words, new_words):
        if left.lower() != right.lower():
            break
        common += 1
    if common >= 2:
        return True
    return False


class TranscriptAssembler:
    """Join Apple utterance finals with the latest partial hypothesis."""

    def __init__(self) -> None:
        self._finals: List[str] = []
        self._partial = ""

    def handle(self, event: Dict[str, Any]) -> None:
        typ = event.get("type")
        text = normalize_transcript(event.get("text") or "")
        if typ == "final":
            if self._partial and self._partial != text and not _is_same_utterance(self._partial, text):
                self._append_final(self._partial)
            self._append_final(text)
            self._partial = ""
        elif typ == "partial":
            if self._partial and text and not _is_same_utterance(self._partial, text):
                self._append_final(self._partial)
            # A newly-created Apple recognition task can replay the words
            # finalized by the previous task. Keep only the genuinely new
            # suffix; otherwise the live transcript shows the phrase twice.
            if self._finals:
                previous = " ".join(self._finals)
                text = _strip_replayed_prefix(previous, text)
                if text == normalize_transcript(event.get("text") or ""):
                    text = _strip_replayed_overlap(previous, text)
                    if text == normalize_transcript(event.get("text") or ""):
                        text = _strip_replayed_leading_overlap(previous, text)
            self._partial = text

    def current_text(self) -> str:
        parts = list(self._finals)
        if self._partial:
            parts.append(self._partial)
        return " ".join(parts).strip()

    def reset(self) -> None:
        self._finals.clear()
        self._partial = ""

    def _append_final(self, text: str) -> None:
        if not text:
            return
        if not self._finals:
            self._finals.append(text)
            return
        previous = " ".join(self._finals)
        # Recognition tasks may finalize the complete hypothesis again after
        # a restart. Merge that repeated prefix instead of appending it twice,
        # even when punctuation or capitalization changed in the replay.
        suffix = _strip_replayed_prefix(previous, text)
        if suffix != text:
            if suffix:
                self._finals.append(suffix)
            return
        self._finals.append(text)


def _peer_pid(conn: socket.socket) -> Optional[int]:
    try:
        data = conn.getsockopt(_SOL_LOCAL, _LOCAL_PEERPID, 4)
        return struct.unpack("i", data)[0]
    except OSError:
        return None


class VoiceSession:
    """Spawn the STT helper and assemble live transcripts until stop()."""

    def __init__(self, command: Optional[List[str]] = None) -> None:
        self._command = command
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._assembler = TranscriptAssembler()
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._dead = threading.Event()
        self._error: Optional[str] = None
        self._stderr = ""
        self._helper_pid: Optional[int] = None
        self._tmpdir: Optional[str] = None
        self._server: Optional[socket.socket] = None
        self._conn: Optional[socket.socket] = None
        self._stream: Optional[Any] = None

    def start(self) -> None:
        if self._command is not None:
            self._start_pipe(self._command)
            return
        self._start_app(ensure_binary())

    def wait_ready(self, timeout: float = 120.0) -> None:
        if not self._ready.wait(timeout):
            self.stop()
            raise RuntimeError(self._format_error("speech helper did not become ready"))
        if self._error:
            message = self._error
            self.stop()
            raise RuntimeError(message)
        if self._dead.is_set():
            self.stop()
            raise RuntimeError(self._format_error("speech helper exited"))

    def current_text(self) -> str:
        with self._lock:
            return self._assembler.current_text()

    def unexpected_exit(self) -> Optional[str]:
        if not self._dead.is_set():
            return None
        if self._error:
            return self._error
        return self._format_error("speech helper exited")

    def stop(self) -> str:
        text = self.current_text()
        pid = self._helper_pid
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1)
        if self._conn is not None:
            try:
                self._conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._conn.close()
            except OSError:
                pass
            self._conn = None
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=1)
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=1)
        if proc is not None:
            if proc.stdout is not None:
                proc.stdout.close()
            if proc.stderr is not None:
                proc.stderr.close()
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None
        self._helper_pid = None
        return text

    def _start_pipe(self, cmd: List[str]) -> None:
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
        self._stream = self._proc.stdout
        self._thread = threading.Thread(target=self._read_events, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._thread.start()
        self._stderr_thread.start()

    def _start_app(self, dest: Path) -> None:
        app = dest if dest.suffix == ".app" else dest
        if app.suffix != ".app":
            self._start_pipe([str(app)])
            return
        exe = app_executable(app)
        if not exe.is_file():
            raise RuntimeError("speech helper app is missing %s" % exe)
        self._tmpdir = tempfile.mkdtemp(prefix="harness-stt-")
        sock_path = os.path.join(self._tmpdir, "s")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(sock_path)
        server.listen(1)
        server.settimeout(15)
        self._server = server
        launch = subprocess.run(
            ["open", "-n", str(app), "--args", "--socket", sock_path],
            capture_output=True,
            text=True,
        )
        if launch.returncode != 0:
            detail = (launch.stderr or launch.stdout or "open failed").strip()
            server.close()
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None
            raise RuntimeError("failed to launch speech helper: %s" % detail)
        try:
            conn, _ = server.accept()
        except socket.timeout:
            server.close()
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None
            raise RuntimeError(
                "speech helper did not connect — allow Microphone and Speech Recognition "
                "in System Settings > Privacy & Security if prompted"
            )
        conn.settimeout(None)
        self._conn = conn
        self._helper_pid = _peer_pid(conn)
        self._stream = conn.makefile("rb")
        self._thread = threading.Thread(target=self._read_events, daemon=True)
        self._thread.start()

    def _read_events(self) -> None:
        stream = self._stream
        if stream is None:
            self._dead.set()
            self._ready.set()
            return
        try:
            for raw in stream:
                try:
                    event = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(event, dict):
                    continue
                typ = event.get("type")
                if typ == "ready":
                    pid = event.get("pid")
                    if isinstance(pid, int):
                        self._helper_pid = pid
                    self._ready.set()
                elif typ == "error":
                    self._error = str(event.get("message") or "speech error")
                    self._dead.set()
                    self._ready.set()
                    break
                elif typ in {"partial", "final"}:
                    with self._lock:
                        self._assembler.handle(event)
        finally:
            self._dead.set()
            self._ready.set()

    def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        chunks: List[bytes] = []
        for raw in proc.stderr:
            chunks.append(raw)
        self._stderr = b"".join(chunks).decode("utf-8", errors="replace")

    def _format_error(self, fallback: str) -> str:
        if self._error:
            return self._error
        detail = self._stderr.strip()
        if detail:
            last = detail.splitlines()[-1]
            if "on-device recognition" in last:
                return (
                    "%s before becoming ready (macOS privacy check). "
                    "If a dialog appeared, allow Microphone and Speech Recognition."
                    % fallback
                )
            return "%s: %s" % (fallback, last)
        return (
            "%s before becoming ready. Allow Microphone and Speech Recognition "
            "in System Settings > Privacy & Security."
            % fallback
        )
