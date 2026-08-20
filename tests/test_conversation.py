import tempfile
import unittest
from pathlib import Path

from harness.conversation import (
    assistant_message,
    conversation_title,
    load_conversation_state,
    load_session_catalog,
    save_conversation_history,
    save_session_catalog,
    session_catalog_path,
    save_conversation_state,
    session_state_path,
    system_message,
    compact_conversation,
    estimate_tokens,
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

    def test_user_message_with_images_uses_content_parts(self):
        image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}
        self.assertEqual(user_message("  describe this  ", [image]), {
            "role": "user",
            "content": [{"type": "text", "text": "describe this"}, image],
        })

    def test_image_token_estimate_does_not_count_base64_payload(self):
        image = {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64," + "A" * 1_000_000},
        }
        self.assertLess(estimate_tokens(user_message("describe", [image])), 400)

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

    def test_state_round_trip_and_session_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            conversation = [system_message("rules"), user_message("hello world")]
            save_conversation_state(path, conversation)
            self.assertEqual(load_conversation_state(path), conversation)
            catalog = Path(directory) / "sessions.json"
            save_session_catalog(catalog, [{"path": str(path), "title": "hello world"}])
            self.assertEqual(load_session_catalog(catalog)[0]["title"], "hello world")
            self.assertEqual(conversation_title(conversation), "hello world")
            self.assertEqual(session_catalog_path(path), catalog)

    def test_session_catalog_keeps_five_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            from harness.conversation import update_session_catalog
            catalog = Path(directory) / "sessions.json"
            for index in range(6):
                state = Path(directory) / f"session-{index}.json"
                update_session_catalog(catalog, state, [user_message(f"request {index}")])
            sessions = load_session_catalog(catalog)
            self.assertEqual(len(sessions), 5)
            self.assertEqual(sessions[0]["title"], "request 5")

    def test_session_catalog_is_filtered_by_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            from harness.conversation import update_session_catalog
            root = Path(directory)
            catalog = root / "sessions.json"
            first = root / "first.json"
            second = root / "second.json"
            update_session_catalog(catalog, first, [user_message("first")], workspace=root / "one")
            update_session_catalog(catalog, second, [user_message("second")], workspace=root / "two")
            self.assertEqual(load_session_catalog(catalog, root / "one")[0]["title"], "first")
            self.assertEqual(load_session_catalog(catalog, root / "two")[0]["title"], "second")

    def test_invalid_state_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            path.write_text('{"version": 1, "conversation": "bad"}', encoding="utf-8")
            self.assertIsNone(load_conversation_state(path))

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
