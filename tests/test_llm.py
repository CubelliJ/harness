import unittest

from harness.llm import _is_rate_limited, parse_tool_call


class LlmTestCase(unittest.TestCase):
    def test_parse_tool_call(self):
        call_id, name, args = parse_tool_call({
            "id": "call-1",
            "function": {"name": "read_file", "arguments": '{"filename":"README.md"}'},
        })
        self.assertEqual((call_id, name, args), ("call-1", "read_file", {"filename": "README.md"}))

    def test_parse_tool_call_handles_invalid_arguments(self):
        self.assertEqual(
            parse_tool_call({"id": "call-1", "function": {"name": "x", "arguments": "not-json"}}),
            ("call-1", "x", {}),
        )

    def test_parse_tool_call_handles_non_object_arguments(self):
        self.assertEqual(
            parse_tool_call({"id": "call-1", "function": {"name": "x", "arguments": "[]"}}),
            ("call-1", "x", {}),
        )

    def test_is_rate_limited(self):
        self.assertTrue(_is_rate_limited(RuntimeError("OpenRouter error: {'code': 429}")))
        self.assertTrue(_is_rate_limited(RuntimeError("temporarily rate-limited upstream")))
        self.assertFalse(_is_rate_limited(RuntimeError("OpenRouter HTTP 500: boom")))


if __name__ == "__main__":
    unittest.main()
