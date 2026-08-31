import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from harness.main import _append_interrupted_tool_results, _context_bar, _select_model
from harness.terminal import MarkdownStreamRenderer, render_markdown


def _catalogue():
    return [
        {"id": "openai/gpt-5", "name": "OpenAI: GPT-5", "context_length": 400000},
        {"id": "z-ai/glm-4.6", "name": "Z.AI: GLM 4.6", "context_length": 200000},
        {"id": "anthropic/claude-4.5", "name": "Anthropic: Claude 4.5"},
    ]


class ModelSearchTests(unittest.TestCase):
    def test_search_text_lists_only_matching_models(self):
        buffer = io.StringIO()
        with patch("harness.main.get_available_models", return_value=_catalogue()), \
                redirect_stdout(buffer):
            result = _select_model("open")
        self.assertIsNone(result)
        output = buffer.getvalue()
        self.assertIn("openai/gpt-5", output)
        self.assertNotIn("z-ai/glm-4.6", output)
        self.assertNotIn("anthropic/claude-4.5", output)
        self.assertIn("1 matching models for 'open'", output)

    def test_search_text_with_number_picks_from_matches(self):
        buffer = io.StringIO()
        with patch("harness.main.get_available_models", return_value=_catalogue()), \
                patch("harness.main.config.set_model") as set_model, \
                redirect_stdout(buffer):
            result = _select_model("z 1")
        self.assertEqual(result, "z-ai/glm-4.6")
        set_model.assert_called_once_with("z-ai/glm-4.6")

    def test_direct_pick_offers_workspace_default(self):
        buffer = io.StringIO()
        with patch("harness.main.get_available_models", return_value=_catalogue()), \
                patch("harness.main.config.set_model") as set_model, \
                patch("harness.main._offer_workspace_default") as offer, \
                redirect_stdout(buffer):
            result = _select_model("2")
        self.assertEqual(result, "z-ai/glm-4.6")
        set_model.assert_called_once_with("z-ai/glm-4.6")
        offer.assert_called_once_with("z-ai/glm-4.6")

    def test_search_text_without_matches_reports_no_results(self):
        buffer = io.StringIO()
        with patch("harness.main.get_available_models", return_value=_catalogue()), \
                redirect_stdout(buffer):
            result = _select_model("qqq")
        self.assertIsNone(result)
        self.assertIn("no models matching", buffer.getvalue())

    def test_exact_id_still_switches_directly(self):
        buffer = io.StringIO()
        with patch("harness.main.get_available_models", return_value=_catalogue()), \
                patch("harness.main.config.set_model") as set_model, \
                redirect_stdout(buffer):
            result = _select_model("z-ai/glm-4.6")
        self.assertEqual(result, "z-ai/glm-4.6")
        set_model.assert_called_once_with("z-ai/glm-4.6")

    def test_out_of_range_number_is_rejected(self):
        buffer = io.StringIO()
        with patch("harness.main.get_available_models", return_value=_catalogue()), \
                redirect_stdout(buffer):
            result = _select_model("99")
        self.assertIsNone(result)
        self.assertIn("enter a model number 1-3", buffer.getvalue())


class InterruptedToolTurnTests(unittest.TestCase):
    def test_closes_all_missing_tool_outputs(self):
        conversation = [
            {"role": "system", "content": "system"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call-1"}, {"id": "call-2"},
            ]},
            {"role": "tool", "tool_call_id": "call-1", "content": "ok"},
        ]
        _append_interrupted_tool_results(conversation)
        self.assertEqual(conversation[-1]["tool_call_id"], "call-2")
        self.assertIn("interrupted by user", conversation[-1]["content"])

    def test_does_not_change_completed_turn(self):
        conversation = [{"role": "assistant", "content": "done"}]
        _append_interrupted_tool_results(conversation)
        self.assertEqual(len(conversation), 1)


class ContextBarTests(unittest.TestCase):
    def test_context_bar_reports_percentage(self):
        self.assertEqual(_context_bar(25, 100, width=10), "[##........] 25%")

    def test_context_bar_handles_unknown_limit(self):
        self.assertEqual(_context_bar(25, None), "[25 tokens; limit unknown]")


class MarkdownStreamTests(unittest.TestCase):
    def test_stream_renderer_flushes_plain_partial_text(self):
        renderer = MarkdownStreamRenderer(color=False)
        self.assertEqual(renderer.feed("Hello"), "Hello")
        self.assertEqual(renderer.feed(", world\n"), ", world\n")

    def test_stream_renderer_buffers_partial_markdown_constructs(self):
        renderer = MarkdownStreamRenderer(color=True)
        self.assertEqual(renderer.feed("## Ti"), "")
        self.assertEqual(renderer.feed("tle\n"), "\033[1;36m## Title\033[0m\n")
        self.assertEqual(renderer.feed("Use `code"), "")
        self.assertIn("code", renderer.feed("` now"))

    def test_stream_renderer_keeps_blocks_buffered_one_token_at_a_time(self):
        renderer = MarkdownStreamRenderer(color=True)
        output = "".join(renderer.feed(character) for character in "### Uncommitted changes\n")
        self.assertIn("\033[1;34m### Uncommitted changes\033[0m\n", output)
        self.assertNotIn("### Uncommitted changes\n", output)

        renderer = MarkdownStreamRenderer(color=True)
        output = "".join(renderer.feed(character) for character in "- **Branch:** `feature/streaming-responses`\n")
        self.assertIn("\033[36m- \033[0m", output)
        self.assertIn("\033[1mBranch:\033[0m", output)
        self.assertNotIn("- **Branch:**", output)

    def test_stream_renderer_preserves_split_bold_markers(self):
        renderer = MarkdownStreamRenderer(color=True)
        self.assertEqual(renderer.feed("This is **bo"), "This is ")
        output = renderer.feed("ld** text.\n")
        self.assertIn("\033[1mbold\033[0m", output)

    def test_stream_renderer_does_not_style_underscore_identifiers_or_arithmetic(self):
        for text in ("Use _stream_completion.\n", "2 * 3\n"):
            renderer = MarkdownStreamRenderer(color=True)
            output = "".join(renderer.feed(character) for character in text)
            self.assertNotIn("\033[3m", output)
            self.assertIn(text, output.replace("\033[0m", ""))

    def test_stream_renderer_keeps_bold_around_underscore_identifiers(self):
        renderer = MarkdownStreamRenderer(color=True)
        output = renderer.feed(
            "- **No test exercises execute_llm_call end-to-end** — test_llm.py only tests _stream_completion.\n"
        )
        self.assertIn("\033[1mNo test exercises execute_llm_call end-to-end\033[0m", output)
        self.assertNotIn("\033[3mllm\033[0m", output)

    def test_stream_renderer_styles_partial_fenced_code_lines(self):
        renderer = MarkdownStreamRenderer(color=True)
        output = renderer.feed("```text\n")
        output += "".join(renderer.feed(character) for character in "print(1)\n")
        output += renderer.feed("```\n")
        self.assertIn("\033[38;5;252;48;5;236mprint(1)\033[0m\n", output)
        self.assertNotIn("print(1)\n", output.replace("\033[38;5;252;48;5;236mprint(1)\033[0m\n", ""))

    def test_stream_renderer_handles_crlf(self):
        renderer = MarkdownStreamRenderer(color=False)
        self.assertEqual(renderer.feed("**bold**\r\n"), "**bold**\n")

    def test_stream_renderer_preserves_markdown_and_fence_state(self):
        renderer = MarkdownStreamRenderer(color=True)
        output = renderer.feed("## Ti")
        self.assertEqual(output, "")
        output += renderer.feed("tle\n```python\nprint('x')\n")
        output += renderer.feed("```\n")
        output += renderer.finish()
        self.assertIn("\033[1;36m## Title\033[0m", output)
        self.assertIn("code python", output)
        self.assertIn("\033[38;5;252;48;5;236mprint('x')", output)
        self.assertIn("└", output)


class TerminalMarkdownTests(unittest.TestCase):
    def test_plain_text_is_unchanged_without_color(self):
        text = "Hello, terminal!\n"
        self.assertEqual(render_markdown(text, color=False), text)

    def test_headings_and_emphasis_are_rendered(self):
        rendered = render_markdown("## Title\n\nThis is **bold** and *italic*.\n", color=True)
        self.assertIn("\033[1;36m## Title\033[0m", rendered)
        self.assertIn("\033[1mbold\033[0m", rendered)
        self.assertIn("\033[3mitalic\033[0m", rendered)

    def test_inline_code_is_not_emphasized(self):
        rendered = render_markdown("Use `**literal**` here.", color=True)
        self.assertIn("\033[30;43m**literal**\033[0m", rendered)
        self.assertNotIn("\033[1m**literal**", rendered)

    def test_fenced_code_preserves_content_and_indentation(self):
        text = "```python\n  print('**literal**')\n```\n"
        rendered = render_markdown(text, color=True)
        self.assertIn("code python", rendered)
        self.assertIn("  print('**literal**')", rendered)
        self.assertNotIn("\033[1m**literal**", rendered)

    def test_lists_and_quotes_keep_their_text(self):
        rendered = render_markdown("- one\n  1. two\n> quoted\n", color=False)
        self.assertEqual(rendered, "- one\n  1. two\n│ quoted\n")

    def test_horizontal_rule_becomes_divider(self):
        rendered = render_markdown("---\n", color=False)
        self.assertEqual(rendered, "─" * 40 + "\n")

    def test_color_can_be_disabled(self):
        rendered = render_markdown("# Heading **bold** `code`\n", color=False)
        self.assertNotIn("\033[", rendered)
        self.assertIn("# Heading **bold** `code`", rendered)


if __name__ == "__main__":
    unittest.main()
