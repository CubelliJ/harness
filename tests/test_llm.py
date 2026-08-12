import unittest

from harness.llm import parse_tool_call


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


if __name__ == "__main__":
    unittest.main()
