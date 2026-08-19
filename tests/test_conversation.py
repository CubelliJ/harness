import tempfile
import unittest
from pathlib import Path

from harness.conversation import (
    assistant_message,
    save_conversation_history,
    system_message,
    compact_conversation,
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

    def test_compact_conversation_preserves_system_and_complete_recent_turn(self):
        conversation = [
            system_message("rules"),
            user_message("old request"),
            assistant_message("old answer"),
            user_message("current request"),
            assistant_message("current answer"),
        ]
        changed = compact_conversation(conversation, 3, token_counter=lambda _: 1)
        self.assertTrue(changed)
        self.assertEqual(conversation[0], system_message("rules"))
        self.assertEqual(conversation[-2:], [user_message("current request"), assistant_message("current answer")])
        self.assertIn("compacted", conversation[1]["content"])

    def test_compact_conversation_does_not_split_tool_exchange(self):
        conversation = [
            system_message("rules"),
            user_message("old request"),
            assistant_message(None, [{"id": "call-1"}]),
            tool_message("call-1", "result"),
            user_message("current request"),
        ]
        compact_conversation(conversation, 4, token_counter=lambda _: 1)
        roles = [message["role"] for message in conversation]
        self.assertEqual(roles, ["system", "system", "user"])
        self.assertEqual(conversation[-1]["content"], "current request")

    def test_manual_compaction_works_without_budget(self):
        conversation = [
            system_message("rules"),
            user_message("old request"),
            assistant_message("old answer"),
            user_message("current request"),
            assistant_message("current answer"),
        ]
        changed = compact_conversation(
            conversation, None, token_counter=lambda _: 1, force=True,
        )
        self.assertTrue(changed)
        self.assertEqual(conversation[0], system_message("rules"))
        self.assertIn("compacted", conversation[1]["content"])

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
