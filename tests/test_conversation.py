import tempfile
import unittest
from pathlib import Path

from harness.conversation import (
    assistant_message,
    save_conversation_history,
    system_message,
    tool_message,
    user_message,
)


class ConversationTestCase(unittest.TestCase):
    def test_message_helpers(self):
        self.assertEqual(system_message("rules"), {"role": "system", "content": "rules"})
        self.assertEqual(user_message("  hello  "), {"role": "user", "content": "hello"})
        self.assertEqual(assistant_message("answer"), {"role": "assistant", "content": "answer"})
        self.assertEqual(tool_message("call-1", "result"), {
            "role": "tool", "tool_call_id": "call-1", "content": "result"
        })

    def test_save_conversation_creates_parent_and_serializes_tool_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "history.txt"
            conversation = [
                system_message("rules"),
                assistant_message("", [{"id": "call-1", "function": {"name": "read_file"}}]),
                tool_message("call-1", "content"),
            ]
            save_conversation_history(path, conversation)
            output = path.read_text(encoding="utf-8")
            self.assertIn("system", output)
            self.assertIn("call-1", output)
            self.assertIn("tool_call_id=call-1", output)
            self.assertIn("content", output)


if __name__ == "__main__":
    unittest.main()
