import io
import unittest
from contextlib import redirect_stdout

from harness.cli.agent_loop import _append_interrupted_tool_results, run_turn


class AgentLoopTestCase(unittest.TestCase):
    def setUp(self):
        self.conversation = [{"role": "system", "content": "system"}]
        self.persisted = 0
        self.compactions = 0
        self.tokens = []

    def _compact(self):
        self.compactions += 1
        return False

    def _persist(self):
        self.persisted += 1

    def _run(self, responses, *, tool_results=None, confirm_command=None,
             confirm_edit=None, auto_approve=False):
        calls = iter(responses)
        tool_results = tool_results or {}

        def interruptible(function, *args, **kwargs):
            if function.__name__ == "execute_llm_call":
                return next(calls)
            name = args[0]
            return tool_results.get(name, {"action": "ok"})

        output = io.StringIO()
        with redirect_stdout(output):
            run_turn(
                self.conversation,
                session_auto_approve=auto_approve,
                compact=self._compact,
                persist=self._persist,
                maybe_generate_title=lambda: None,
                confirm_command=confirm_command or (lambda command: (True, "")),
                confirm_edit=confirm_edit or (lambda result: (True, "")),
                interruptible_call=interruptible,
                update_tokens=self.tokens.append,
            )
        return output.getvalue()

    def test_plain_response_updates_conversation_and_usage(self):
        output = self._run([("Hello", [], {"prompt_tokens": 12})])
        self.assertEqual(self.conversation[-1]["role"], "assistant")
        self.assertEqual(self.conversation[-1]["content"], "Hello")
        self.assertEqual(self.tokens, [12])
        self.assertEqual(self.persisted, 1)
        self.assertEqual(self.compactions, 1)
        self.assertIn("Hello", output)

    def test_streamed_response_is_not_printed_twice(self):
        def interruptible(function, *args, **kwargs):
            if function.__name__ == "execute_llm_call":
                callback = kwargs["on_text"]
                callback("Hel")
                callback("lo")
                return "Hello", [], {}
            raise AssertionError("no tool call expected")

        with redirect_stdout(io.StringIO()) as output:
            run_turn(
                self.conversation,
                session_auto_approve=False,
                compact=lambda: False,
                persist=lambda: None,
                maybe_generate_title=lambda: None,
                confirm_command=lambda command: (True, ""),
                confirm_edit=lambda result: (True, ""),
                interruptible_call=interruptible,
                update_tokens=lambda tokens: None,
            )
        self.assertEqual(output.getvalue().count("Hello"), 1)

    def test_tool_turn_executes_tool_then_continues_to_final_response(self):
        tool_call = {
            "id": "call-1",
            "function": {"name": "read_file", "arguments": '{"filename":"README.md"}'},
        }
        output = self._run([
            (None, [tool_call], {"prompt_tokens": 20}),
            ("Done", [], {"prompt_tokens": 30}),
        ], tool_results={"read_file": {"file_path": "README.md", "content": "ok"}})
        self.assertEqual(self.conversation[-1]["content"], "Done")
        self.assertEqual([message["role"] for message in self.conversation],
                         ["system", "assistant", "tool", "assistant"])
        self.assertEqual(self.persisted, 3)
        self.assertIn("read_file", output)

    def test_command_rejection_adds_feedback_without_running_tool(self):
        tool_call = {
            "id": "call-1",
            "function": {"name": "run_command", "arguments": '{"command":"rm -rf tmp"}'},
        }
        executed = []
        responses = iter([(None, [tool_call], {}), ("Stopped", [], {})])

        def interruptible(function, *args, **kwargs):
            if function.__name__ == "execute_llm_call":
                return next(responses)
            executed.append(args)
            return {"passed": True}

        with redirect_stdout(io.StringIO()):
            run_turn(
                self.conversation,
                session_auto_approve=False,
                compact=lambda: False,
                persist=lambda: None,
                maybe_generate_title=lambda: None,
                confirm_command=lambda command: (False, "unsafe"),
                confirm_edit=lambda result: (True, ""),
                interruptible_call=interruptible,
                update_tokens=lambda tokens: None,
            )
        self.assertEqual(executed, [])
        self.assertIn("command_rejected", self.conversation[-2]["content"])
        self.assertIn("unsafe", self.conversation[-2]["content"])

    def test_malformed_tool_call_becomes_tool_error(self):
        malformed = {"id": "bad", "function": {"name": "read_file", "arguments": "not-json"}}
        self._run([(None, [malformed], {}), ("Recovered", [], {})])
        self.assertIn("invalid JSON arguments", self.conversation[2]["content"])
        self.assertEqual(self.conversation[-1]["content"], "Recovered")

    def test_image_tool_adds_visual_context_message(self):
        tool_call = {
            "id": "image-1",
            "function": {"name": "read_image", "arguments": '{"filename":"diagram.png"}'},
        }
        self._run(
            [(None, [tool_call], {}), ("I see it", [], {})],
            tool_results={"read_image": {"file_path": "diagram.png", "image_url": "data:image/png;base64,x"}},
        )
        image_message = self.conversation[3]
        self.assertEqual(image_message["role"], "user")
        self.assertTrue(image_message["image_context"])
        self.assertEqual(image_message["content"][1]["type"], "image_url")


class InterruptedToolRepairTests(unittest.TestCase):
    def test_repairs_only_missing_tool_results(self):
        conversation = [{
            "role": "assistant",
            "tool_calls": [{"id": "one"}, {"id": "two"}],
        }, {"role": "tool", "tool_call_id": "one", "content": "ok"}]
        _append_interrupted_tool_results(conversation)
        self.assertEqual(conversation[-1]["tool_call_id"], "two")
        self.assertIn("interrupted by user", conversation[-1]["content"])


if __name__ == "__main__":
    unittest.main()
