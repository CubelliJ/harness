import unittest
from unittest.mock import patch

from harness.llm import _is_rate_limited, get_available_models, model_context_length, parse_tool_call


class LlmTestCase(unittest.TestCase):
    def test_parse_tool_call(self):
        call_id, name, args = parse_tool_call({
            "id": "call-1",
            "function": {"name": "read_file", "arguments": '{"filename":"README.md"}'},
        })
        self.assertEqual((call_id, name, args), ("call-1", "read_file", {"filename": "README.md"}))

    def test_parse_tool_call_handles_invalid_arguments(self):
        with self.assertRaisesRegex(ValueError, "invalid JSON arguments"):
            parse_tool_call({
                "id": "call-1",
                "function": {"name": "x", "arguments": "not-json"},
            })

    def test_parse_tool_call_handles_non_object_arguments(self):
        with self.assertRaisesRegex(ValueError, "must decode to an object"):
            parse_tool_call({
                "id": "call-1",
                "function": {"name": "x", "arguments": "[]"},
            })

    def test_model_context_length(self):
        body = {"data": [{"id": "model-a", "context_length": 128000}]}
        self.assertEqual(model_context_length(body, "model-a"), 128000)
        self.assertIsNone(model_context_length(body, "missing"))

    @patch("harness.llm._models_response")
    def test_available_models_filters_and_sorts(self, response):
        response.return_value = {"data": [
            {"id": "z/model", "name": "Zed"},
            {"id": "a/model", "name": "Alpha"},
            {"id": "ignored", "name": ""},
            {"name": "missing id"},
        ]}
        self.assertEqual([m["id"] for m in get_available_models()], ["a/model", "ignored", "z/model"])

    def test_is_rate_limited(self):
        self.assertTrue(_is_rate_limited(RuntimeError("OpenRouter error: {'code': 429}")))
        self.assertTrue(_is_rate_limited(RuntimeError("temporarily rate-limited upstream")))
        self.assertFalse(_is_rate_limited(RuntimeError("OpenRouter HTTP 500: boom")))


if __name__ == "__main__":
    unittest.main()
