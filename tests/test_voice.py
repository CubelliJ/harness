import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from harness.main import _rows_for_voice_line, _visible_len
from harness.voice import (
    TranscriptAssembler,
    VoiceSession,
    ensure_binary,
    is_supported,
)


_FAKE_HELPER = r"""
import json
import sys
import time

def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()

mode = sys.argv[1] if len(sys.argv) > 1 else "ok"
if mode == "error":
    emit({"type": "error", "message": "boom"})
    sys.exit(1)
if mode == "hang":
    time.sleep(30)
    sys.exit(0)
emit({"type": "ready"})
emit({"type": "partial", "text": "hello"})
time.sleep(0.05)
emit({"type": "final", "text": "hello world"})
emit({"type": "partial", "text": "again"})
time.sleep(30)
"""


def _write_helper(directory: str) -> str:
    path = Path(directory) / "fake_stt.py"
    path.write_text(_FAKE_HELPER, encoding="utf-8")
    return str(path)


class TranscriptAssemblerTests(unittest.TestCase):
    def test_empty_until_events(self):
        assembler = TranscriptAssembler()
        self.assertEqual(assembler.current_text(), "")

    def test_partial_replaced_not_appended(self):
        assembler = TranscriptAssembler()
        assembler.handle({"type": "partial", "text": "hel"})
        assembler.handle({"type": "partial", "text": "hello"})
        self.assertEqual(assembler.current_text(), "hello")

    def test_finals_join_with_latest_partial(self):
        assembler = TranscriptAssembler()
        assembler.handle({"type": "final", "text": "hello world"})
        assembler.handle({"type": "partial", "text": "again"})
        self.assertEqual(assembler.current_text(), "hello world again")

    def test_final_clears_partial_and_ignores_blank(self):
        assembler = TranscriptAssembler()
        assembler.handle({"type": "partial", "text": "hello"})
        assembler.handle({"type": "final", "text": "hello"})
        assembler.handle({"type": "final", "text": "  "})
        self.assertEqual(assembler.current_text(), "hello")

    def test_unknown_events_are_ignored(self):
        assembler = TranscriptAssembler()
        assembler.handle({"type": "ready"})
        assembler.handle({"type": "partial", "text": "hi"})
        self.assertEqual(assembler.current_text(), "hi")

    def test_reset_clears_state(self):
        assembler = TranscriptAssembler()
        assembler.handle({"type": "final", "text": "one"})
        assembler.handle({"type": "partial", "text": "two"})
        assembler.reset()
        self.assertEqual(assembler.current_text(), "")

    def test_unrelated_partial_keeps_previous_utterance(self):
        assembler = TranscriptAssembler()
        assembler.handle({"type": "partial", "text": "the word is chicken"})
        assembler.handle({"type": "partial", "text": "what the word is"})
        self.assertEqual(assembler.current_text(), "the word is chicken what the word is")

    def test_short_new_partial_does_not_eat_previous_sentence(self):
        assembler = TranscriptAssembler()
        assembler.handle({"type": "partial", "text": "the word is chicken"})
        assembler.handle({"type": "partial", "text": "the"})
        self.assertEqual(assembler.current_text(), "the word is chicken the")

    def test_newlines_are_collapsed_not_treated_as_reset(self):
        assembler = TranscriptAssembler()
        assembler.handle({"type": "partial", "text": "the word is chicken\nwhat the word is"})
        self.assertEqual(assembler.current_text(), "the word is chicken what the word is")

    def test_duplicate_final_is_not_repeated(self):
        assembler = TranscriptAssembler()
        assembler.handle({"type": "partial", "text": "hello"})
        assembler.handle({"type": "final", "text": "hello"})
        assembler.handle({"type": "final", "text": "hello"})
        self.assertEqual(assembler.current_text(), "hello")


class VoiceSessionTests(unittest.TestCase):
    def _wait_for(self, session: VoiceSession, expected: str, timeout: float = 2.0) -> str:
        deadline = time.time() + timeout
        text = ""
        while time.time() < deadline:
            text = session.current_text()
            if text == expected:
                return text
            time.sleep(0.02)
        return text

    def test_assembles_finals_and_partial_from_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = _write_helper(directory)
            session = VoiceSession(command=[sys.executable, helper, "ok"])
            session.start()
            try:
                session.wait_ready(timeout=5)
                text = self._wait_for(session, "hello world again")
                self.assertEqual(text, "hello world again")
            finally:
                stopped = session.stop()
            self.assertEqual(stopped, "hello world again")

    def test_error_event_fails_wait_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = _write_helper(directory)
            session = VoiceSession(command=[sys.executable, helper, "error"])
            session.start()
            with self.assertRaises(RuntimeError) as ctx:
                session.wait_ready(timeout=5)
            self.assertIn("boom", str(ctx.exception))

    def test_ready_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = _write_helper(directory)
            session = VoiceSession(command=[sys.executable, helper, "hang"])
            session.start()
            with self.assertRaises(RuntimeError) as ctx:
                session.wait_ready(timeout=0.2)
            self.assertIn("did not become ready", str(ctx.exception))


class VoiceDisplayTests(unittest.TestCase):
    def test_visible_len_ignores_ansi(self):
        self.assertEqual(_visible_len("\033[96m▸ You:\033[0m hello"), len("▸ You: hello"))

    def test_short_line_is_one_row(self):
        self.assertEqual(_rows_for_voice_line("hello", width=80), 1)

    def test_wrapped_line_uses_multiple_rows(self):
        self.assertEqual(_rows_for_voice_line("a" * 81, width=80), 2)
        self.assertEqual(_rows_for_voice_line("a" * 160, width=80), 2)
        self.assertEqual(_rows_for_voice_line("a" * 161, width=80), 3)


class VoiceSupportTests(unittest.TestCase):
    def test_is_supported_matches_platform(self):
        self.assertEqual(is_supported(), sys.platform == "darwin")

    def test_ensure_binary_rejects_non_macos(self):
        with patch("harness.voice.sys.platform", "linux"):
            with self.assertRaises(RuntimeError) as ctx:
                ensure_binary()
            self.assertIn("macOS", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
