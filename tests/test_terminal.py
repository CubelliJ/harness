import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from harness.main import _append_interrupted_tool_results, _context_bar, _select_model
from harness.terminal import render_markdown


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
