import tempfile
import unittest
from pathlib import Path

from harness.main import _clipboard_image_part, _context_bar, _extract_pasted_images
from harness.terminal import render_markdown


class ContextBarTests(unittest.TestCase):
    def test_clipboard_image_requires_macos(self):
        import harness.main as main_module
        original_platform = main_module.sys.platform
        try:
            main_module.sys.platform = "linux"
            with self.assertRaisesRegex(ValueError, "only on macOS"):
                _clipboard_image_part()
        finally:
            main_module.sys.platform = original_platform

    def test_extracts_shell_escaped_dropped_image_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Screenshot 2026.png"
            path.write_bytes(b"png")
            text, images = _extract_pasted_images(
                "please inspect " + str(path).replace(" ", "\\ ")
            )
            self.assertEqual(text, "please inspect")
            self.assertEqual(len(images), 1)
            self.assertTrue(images[0]["image_url"]["url"].startswith("data:image/png;base64,"))

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
