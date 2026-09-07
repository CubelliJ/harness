import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


SCRIPT = (
    Path(__file__).parents[1]
    / ".harness"
    / "skills"
    / "copy-to-slack"
    / "scripts"
    / "copy_to_slack.py"
)


spec = importlib.util.spec_from_file_location("copy_to_slack", SCRIPT)
copy_to_slack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(copy_to_slack)


class CopyToSlackTests(unittest.TestCase):
    def run_main(self, args=(), stdin=""):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("sys.argv", [str(SCRIPT), *args]), patch(
            "sys.stdin", io.StringIO(stdin)
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            result = copy_to_slack.main()
        return result, stdout.getvalue(), stderr.getvalue()

    def test_rejects_non_macos(self):
        with patch.object(copy_to_slack.platform, "system", return_value="Linux"):
            result, stdout, stderr = self.run_main(stdin="plain")
        self.assertEqual(result, 2)
        self.assertEqual(stdout, "")
        self.assertIn("requires macOS", stderr)

    def test_sends_html_and_plain_text_without_interpolating_content(self):
        html = (
            '<p><strong>Hello</strong> <em>world</em> &amp; '
            '<code>`$HOME`</code></p>\n<ul><li>Item</li></ul>\n'
            '<pre><code>print(1)</code></pre>'
        )
        plain = "Hello world & ` $HOME `\n\n- Item\n\nprint(1)"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as file:
            file.write(html)
            file.flush()
            with patch.object(
                copy_to_slack.platform, "system", return_value="Darwin"
            ), patch.object(copy_to_slack.subprocess, "run") as run:
                result, stdout, stderr = self.run_main(
                    args=("--html-file", file.name), stdin=plain
                )
        self.assertEqual(result, 0)
        self.assertIn("Copied Slack", stdout)
        self.assertEqual(stderr, "")
        args, kwargs = run.call_args
        self.assertEqual(args, (["osascript", "-l", "JavaScript"],))
        self.assertEqual(kwargs["input"], copy_to_slack.JXA)
        self.assertEqual(kwargs["text"], True)
        self.assertEqual(kwargs["check"], True)
        payload = json.loads(kwargs["env"]["HARNESS_CLIPBOARD_PAYLOAD"])
        self.assertEqual(payload, {"html": html, "plain": plain})

    def test_sanitizes_active_html_but_preserves_safe_links(self):
        source = (
            '<p><a href="https://example.com" title="Docs">Docs</a></p>'
            '<script>alert(1)</script><style>body{}</style>'
            '<p onclick="alert(2)">Text <em>kept</em></p>'
            '<a href="javascript:alert(3)">unsafe</a>'
            '<iframe src="https://example.com"></iframe>'
        )
        sanitized = copy_to_slack.sanitize_html(source)
        self.assertIn('<a href="https://example.com" title="Docs">Docs</a>', sanitized)
        self.assertIn("<em>kept</em>", sanitized)
        self.assertIn(">unsafe</a>", sanitized)
        self.assertNotIn("<script", sanitized)
        self.assertNotIn("alert(1)", sanitized)
        self.assertNotIn("<style", sanitized)
        self.assertNotIn("onclick", sanitized)
        self.assertNotIn("<iframe", sanitized)
        self.assertNotIn("javascript:", sanitized)

    def test_reports_missing_osascript(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as file:
            file.write("<p>text</p>")
            file.flush()
            with patch.object(
                copy_to_slack.platform, "system", return_value="Darwin"
            ), patch.object(
                copy_to_slack.subprocess,
                "run",
                side_effect=FileNotFoundError,
            ):
                result, _, stderr = self.run_main(
                    args=("--html-file", file.name), stdin="text"
                )
        self.assertEqual(result, 1)
        self.assertIn("osascript was not found", stderr)

    def test_reports_osascript_failure_without_leaking_content(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as file:
            file.write("<p>sensitive html</p>")
            file.flush()
            with patch.object(
                copy_to_slack.platform, "system", return_value="Darwin"
            ), patch.object(
                copy_to_slack.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(1, ["osascript"]),
            ):
                result, stdout, stderr = self.run_main(
                    args=("--html-file", file.name), stdin="sensitive plain"
                )
        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("exit code 1", stderr)
        self.assertNotIn("sensitive", stderr)


if __name__ == "__main__":
    unittest.main()
