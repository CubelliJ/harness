import tempfile
import unittest
from pathlib import Path

from harness.conversation import (
    assistant_message,
    conversation_cost,
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
    estimated_usage_cost,
    usage_cost_breakdown,
    usage_cost_fields,
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

    def test_conversation_cost_aggregates_provider_usage(self):
        conversation = [
            system_message("rules"),
            assistant_message("one", usage={
                "prompt_tokens": 10, "prompt_tokens_details": {"cached_tokens": 3},
                "completion_tokens": 4, "total_tokens": 14,
                "cost": 0.001,
            }),
            assistant_message("two", usage={
                "prompt_tokens": 20, "completion_tokens": 6, "total_tokens": 26,
                "cost": 0.002,
            }),
        ]
        summary = conversation_cost(conversation)
        self.assertEqual(summary["calls"], 2)
        self.assertEqual(summary["prompt_tokens"], 30)
        self.assertEqual(summary["completion_tokens"], 10)
        self.assertEqual(summary["cached_input_tokens"], 3)
        self.assertEqual(summary["total_tokens"], 40)
        self.assertAlmostEqual(summary["cost"], 0.003)
        self.assertEqual(summary["last_usage"]["cost"], 0.002)

    def test_usage_cost_fields_normalizes_cache_read_write_and_reasoning(self):
        fields = usage_cost_fields({
            "input_tokens": 100,
            "cache_read_input_tokens": 40,
            "cache_creation_input_tokens": 12,
            "output_tokens": 20,
            "reasoning_output_tokens": 7,
            "total_tokens": 120,
        })
        self.assertEqual(fields, {
            "input_tokens": 100,
            "cache_read_input_tokens": 40,
            "cache_write_input_tokens": 12,
            "output_tokens": 20,
            "reasoning_tokens": 7,
            "total_tokens": 120,
        })

    def test_estimated_usage_cost_separates_fresh_and_cached_input(self):
        costs = estimated_usage_cost(
            {
                "prompt_tokens": 1000,
                "prompt_tokens_details": {"cached_tokens": 700},
                "cache_creation_input_tokens": 100,
                "completion_tokens": 200,
            },
            input_cost_per_million=1.0,
            cache_read_cost_per_million=0.1,
            cache_write_cost_per_million=0.5,
            output_cost_per_million=2.0,
        )
        self.assertAlmostEqual(costs["input_cost"], 0.0002)
        self.assertAlmostEqual(costs["cache_read_cost"], 0.00007)
        self.assertAlmostEqual(costs["cache_write_cost"], 0.00005)
        self.assertAlmostEqual(costs["output_cost"], 0.0004)
        self.assertIsNone(costs["reasoning_cost"])

    def test_usage_cost_breakdown_reads_provider_category_costs(self):
        breakdown = usage_cost_breakdown({
            "cost": 0.01,
            "cost_details": {
                "input_cost": 0.001,
                "cache_read_cost": 0.002,
                "cache_write_cost": 0.003,
                "output_cost": 0.004,
                "reasoning_cost": 0.0005,
            },
        })
        self.assertEqual(breakdown, {
            "input_cost": 0.001,
            "cache_read_cost": 0.002,
            "cache_write_cost": 0.003,
            "output_cost": 0.004,
            "reasoning_cost": 0.0005,
        })

    def test_conversation_cost_aggregates_category_costs_and_unknowns(self):
        conversation = [
            assistant_message("one", usage={
                "cost": 0.01,
                "cost_details": {
                    "input_cost": 0.001,
                    "cache_read_cost": 0.002,
                    "cache_write_cost": 0.003,
                    "output_cost": 0.004,
                    "reasoning_cost": 0.0005,
                },
            }),
            assistant_message("two", usage={
                "cost": 0.02,
                "cost_details": {
                    "input_cost": 0.01,
                    "cache_read_cost": 0.01,
                    "cache_write_cost": 0.01,
                    "output_cost": 0.01,
                    "reasoning_cost": 0.01,
                },
            }),
        ]
        summary = conversation_cost(conversation)
        self.assertAlmostEqual(summary["cost_breakdown"]["input_cost"], 0.011)
        self.assertAlmostEqual(summary["cost_breakdown"]["cache_read_cost"], 0.012)
        self.assertAlmostEqual(summary["cost_breakdown"]["cache_write_cost"], 0.013)
        self.assertAlmostEqual(summary["cost_breakdown"]["output_cost"], 0.014)
        self.assertAlmostEqual(summary["cost_breakdown"]["reasoning_cost"], 0.0105)
        self.assertEqual(
            conversation_cost([assistant_message("two", usage={"cost": 0.02})])["cost_breakdown"],
            {key: None for key in summary["cost_breakdown"]},
        )

    def test_conversation_cost_includes_detailed_token_categories(self):
        conversation = [
            assistant_message("answer", usage={
                "prompt_tokens": 100,
                "prompt_tokens_details": {"cached_tokens": 40},
                "completion_tokens": 20,
                "completion_tokens_details": {"reasoning_tokens": 7},
                "total_tokens": 120,
                "cost": 0.004,
            }),
            {"role": "system", "content": "handover", "compaction_usage": {
                "input_tokens": 50,
                "cache_creation_input_tokens": 12,
                "output_tokens": 5,
                "total_tokens": 55,
                "cost": 0.001,
            }},
        ]
        summary = conversation_cost(conversation)
        self.assertEqual(summary["input_tokens"], 150)
        self.assertEqual(summary["cache_read_input_tokens"], 40)
        self.assertEqual(summary["cache_write_input_tokens"], 12)
        self.assertEqual(summary["output_tokens"], 25)
        self.assertEqual(summary["reasoning_tokens"], 7)
        self.assertEqual(summary["total_tokens"], 175)
        self.assertAlmostEqual(summary["cost"], 0.005)

    def test_conversation_cost_marks_missing_cost_unknown(self):
        summary = conversation_cost([assistant_message("answer", usage={"total_tokens": 3})])
        self.assertIsNone(summary["cost"])

    def test_image_token_estimate_ignores_base64_payload(self):
        image = {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 1000000}}
        estimate = estimate_tokens(user_message("describe", [image]))
        self.assertGreaterEqual(estimate, 1000)
        self.assertLess(estimate, 1020)

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

    def test_automatic_compaction_removes_all_older_turns(self):
        conversation = [
            system_message("rules"),
            user_message("first request"),
            assistant_message("first answer"),
            user_message("second request"),
            assistant_message("second answer"),
            user_message("current request"),
            assistant_message("current answer"),
        ]
        changed = compact_conversation(
            conversation, 1, token_counter=lambda _: 1,
        )
        self.assertTrue(changed)
        self.assertEqual(
            [message.get("content") for message in conversation[2:]],
            ["current request", "current answer"],
        )

    def test_compaction_uses_handover_summary_and_usage(self):
        conversation = [
            system_message("rules"),
            user_message("old request"),
            assistant_message("old answer"),
            user_message("current request"),
            assistant_message("current answer"),
        ]
        calls = []

        def summarize(history):
            calls.append(history)
            return "Goal: continue the implementation.\nNext: run tests.", {"prompt_tokens": 9}

        changed = compact_conversation(
            conversation, 3, token_counter=lambda _: 1, summarize=summarize,
        )
        self.assertTrue(changed)
        self.assertEqual(len(calls), 1)
        self.assertIn("Goal: continue", conversation[1]["content"])
        self.assertEqual(conversation[1]["compaction_usage"]["prompt_tokens"], 9)
        self.assertEqual(conversation[-2:], [user_message("current request"), assistant_message("current answer")])

    def test_compaction_calls_on_start_after_finding_removable_history(self):
        conversation = [
            system_message("rules"),
            user_message("old request"),
            assistant_message("old answer"),
            user_message("current request"),
        ]
        started = []
        changed = compact_conversation(
            conversation,
            3,
            token_counter=lambda _: 1,
            on_start=lambda: started.append(True),
        )
        self.assertTrue(changed)
        self.assertEqual(started, [True])

    def test_automatic_compaction_does_not_replace_existing_handover(self):
        handover = system_message("[Conversation handover]\nkeep this summary")
        conversation = [
            system_message("rules"),
            handover,
            user_message("current request"),
            assistant_message("current answer"),
            user_message("Visual context loaded", [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}]),
        ]
        conversation[-1]["image_context"] = True
        started = []
        changed = compact_conversation(
            conversation,
            1,
            token_counter=lambda _: 1,
            on_start=lambda: started.append(True),
        )
        self.assertFalse(changed)
        self.assertEqual(started, [])
        self.assertEqual(conversation[1], handover)

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

    def test_manual_compaction_removes_all_older_turns(self):
        conversation = [
            system_message("rules"),
            user_message("first request"),
            assistant_message("first answer"),
            user_message("second request"),
            assistant_message("second answer"),
            user_message("current request"),
            assistant_message("current answer"),
        ]
        changed = compact_conversation(
            conversation, None, token_counter=lambda _: 1, force=True,
        )
        self.assertTrue(changed)
        self.assertEqual(
            [message.get("content") for message in conversation[2:]],
            ["current request", "current answer"],
        )

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
