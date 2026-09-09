import json
import os
import unittest
from unittest.mock import patch

from harness.llm import (
    _api_messages,
    _is_rate_limited,
    _stream_completion,
    filter_models,
    generate_conversation_title,
    get_available_models,
    model_context_length,
    parse_tool_call,
    summarize_conversation,
)


class LlmTestCase(unittest.TestCase):
    def test_api_messages_preserves_multimodal_user_content(self):
        image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}
        messages = _api_messages([{"role": "user", "content": [{"type": "text", "text": "look"}, image]}])
        self.assertEqual(messages[0]["content"][1], image)

    def test_stream_completion_delivers_text_and_reassembles_tool_calls(self):
        chunks = [
            b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n',
            b'data: {"choices":[{"delta":{"content":"lo"}}]}\n',
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","type":"function","function":{"name":"read_"}}]}}]}\n',
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"file","arguments":"{\\"filename\\":"}}]}}]}\n',
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"README.md\\"}"}}]}}]}\n',
            b'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2}}\n',
            b'data: [DONE]\n',
        ]
        received = []
        content, tools, usage = _stream_completion(chunks, received.append)
        self.assertEqual(content, "Hello")
        self.assertEqual(received, ["Hel", "lo"])
        self.assertEqual(tools[0]["function"], {"name": "read_file", "arguments": '{"filename":"README.md"}'})
        self.assertEqual(usage["prompt_tokens"], 4)

    def test_stream_completion_updates_expanding_repeated_function_name(self):
        chunks = [
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","function":{"name":"read_"}}]}}]}\n',
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"read_file","arguments":"{}"}}]}}]}\n',
            b'data: [DONE]\n',
        ]
        _, tools, _ = _stream_completion(chunks)
        self.assertEqual(tools[0]["function"]["name"], "read_file")

    def test_stream_completion_allows_empty_completed_response(self):
        content, tools, usage = _stream_completion([b'data: [DONE]\n'])
        self.assertEqual((content, tools, usage), ("", [], {}))

    def test_stream_completion_rejects_truncated_stream(self):
        with self.assertRaisesRegex(RuntimeError, "before \\[DONE\\]"):
            _stream_completion([b'data: {"choices":[{"delta":{"content":"partial"}}]}\n'])

    def test_stream_completion_rejects_tool_without_id(self):
        chunks = [
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"read_file","arguments":"{}"}}]}}]}\n',
            b'data: [DONE]\n',
        ]
        with self.assertRaisesRegex(RuntimeError, "without an id"):
            _stream_completion(chunks)

    def test_stream_completion_handles_interleaved_tool_calls(self):
        chunks = [
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"id":"two","function":{"name":"read_file","arguments":"{\\"filename\\":"}}]}}]}\n',
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"one","function":{"name":"list_files","arguments":"{}"}}]}}]}\n',
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"function":{"arguments":"\\"README.md\\"}"}}]}}]}\n',
            b'data: [DONE]\n',
        ]
        _, tools, _ = _stream_completion(chunks)
        self.assertEqual([call["id"] for call in tools], ["one", "two"])
        self.assertEqual(tools[1]["function"]["arguments"], '{"filename":"README.md"}')

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

    @patch("harness.llm.urllib.request.urlopen")
    @patch.dict(os.environ, {"HARNESS_AUTH_MODE": "none", "HARNESS_MODEL": "example-model"}, clear=True)
    def test_generate_conversation_title_uses_bounded_tool_free_excerpt(self, urlopen):
        response = unittest.mock.Mock()
        response.__enter__ = lambda self: self
        response.__exit__ = lambda *args: None
        response.read.return_value = b'{"choices":[{"message":{"content":"Fix Login Flow."}}]}'
        urlopen.return_value = response
        title = generate_conversation_title([
            {"role": "system", "content": "private system prompt"},
            {"role": "user", "content": "A" * 2000},
            {"role": "assistant", "content": "answer"},
        ])
        self.assertEqual(title, "Fix Login Flow")
        request = urlopen.call_args.args[0]
        payload = __import__("json").loads(request.data)
        self.assertEqual(payload["tools"], [])
        self.assertEqual(payload["tool_choice"], "none")
        self.assertLessEqual(len(payload["messages"][1]["content"]), 1200)

    @patch("harness.llm.urllib.request.urlopen")
    @patch.dict(os.environ, {"HARNESS_AUTH_MODE": "none", "HARNESS_MODEL": "example-model"}, clear=True)
    def test_summarize_conversation_reuses_history_as_prefix(self, urlopen):
        response = unittest.mock.Mock()
        response.__enter__ = lambda self: self
        response.__exit__ = lambda *args: None
        response.read.return_value = b'{"choices":[{"message":{"content":"handover"}}],"usage":{"prompt_tokens":100,"prompt_tokens_details":{"cached_tokens":90}}}'
        urlopen.return_value = response
        history = [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "request"},
        ]
        summary, usage = summarize_conversation(history)
        self.assertEqual(summary, "handover")
        self.assertEqual(usage["prompt_tokens_details"]["cached_tokens"], 90)
        payload = __import__("json").loads(urlopen.call_args.args[0].data)
        self.assertEqual(payload["messages"][:2], history)
        self.assertEqual(payload["tools"], [])
        self.assertEqual(payload["tool_choice"], "none")
        self.assertIn("handover", payload["messages"][-1]["content"])

    @patch("harness.llm._models_response", side_effect=OSError("unavailable"))
    @patch.dict(os.environ, {"HARNESS_MODEL": "example-model", "HARNESS_AUTH_MODE": "none"}, clear=True)
    def test_available_models_falls_back_to_configured_model(self, _response):
        self.assertEqual(get_available_models(), [{"id": "example-model", "name": "example-model"}])

    @patch("harness.llm.urllib.request.urlopen")
    @patch.dict(os.environ, {
        "HARNESS_MODELS_URL": "https://gateway.example.com/models",
        "HARNESS_AUTH_MODE": "none",
        "HARNESS_MODEL": "example-model",
    }, clear=True)
    def test_models_use_configured_url_and_preserve_context_length(self, urlopen):
        response = unittest.mock.Mock()
        response.__enter__ = lambda self: self
        response.__exit__ = lambda *args: None
        response.read.return_value = json.dumps({"data": [
            {"id": "model-b"},
            {"id": "model-a", "name": "Model A", "context_length": 8192},
        ]}).encode()
        urlopen.return_value = response
        models = get_available_models()
        self.assertEqual([model["id"] for model in models], ["model-a", "model-b"])
        self.assertEqual(models[0]["context_length"], 8192)
        self.assertEqual(urlopen.call_args.args[0].full_url, "https://gateway.example.com/models")
        self.assertNotIn("Authorization", urlopen.call_args.args[0].headers)

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

    def test_filter_models_matches_id_and_name(self):
        models = [
            {"id": "openai/gpt-5", "name": "OpenAI: GPT-5"},
            {"id": "z-ai/glm-4.6", "name": "Z.AI: GLM 4.6"},
            {"id": "mistralai/devstral", "name": "Mistral Devstral"},
        ]
        self.assertEqual([m["id"] for m in filter_models(models, "open")], ["openai/gpt-5"])
        self.assertEqual(
            [m["id"] for m in filter_models(models, "glm")],
            ["z-ai/glm-4.6"],
        )
        # Search is case-insensitive and also matches the display name.
        self.assertEqual([m["id"] for m in filter_models(models, "MISTRAL")], ["mistralai/devstral"])
        # An empty query keeps the full catalogue.
        self.assertEqual(len(filter_models(models, "  ")), 3)
        self.assertEqual(filter_models(models, "nope"), [])

    def test_is_rate_limited(self):
        self.assertTrue(_is_rate_limited(RuntimeError("OpenRouter error: {'code': 429}")))
        self.assertTrue(_is_rate_limited(RuntimeError("temporarily rate-limited upstream")))
        self.assertFalse(_is_rate_limited(RuntimeError("OpenRouter HTTP 500: boom")))


if __name__ == "__main__":
    unittest.main()
