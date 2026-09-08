import importlib.util
import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


SCRIPT = (
    Path(__file__).parents[1]
    / "harness"
    / "skills"
    / "copy-to-clipboard"
    / "scripts"
    / "copy_to_clipboard.py"
)


spec = importlib.util.spec_from_file_location("copy_to_clipboard", SCRIPT)
copy_to_clipboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(copy_to_clipboard)


class CopyToClipboardTests(unittest.TestCase):
    def run_main(self, args=(), stdin=""):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("sys.argv", [str(SCRIPT), *args]), patch(
            "sys.stdin", io.StringIO(stdin)
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            result = copy_to_clipboard.main()
        return result, stdout.getvalue(), stderr.getvalue()

    def test_rejects_non_macos_without_reading_or_running_pbcopy(self):
        with patch.object(copy_to_clipboard.platform, "system", return_value="Linux"):
            result, stdout, stderr = self.run_main(stdin="secret")
        self.assertEqual(result, 2)
        self.assertEqual(stdout, "")
        self.assertIn("requires macOS", stderr)

    def test_copies_stdin_without_shell_interpolation(self):
        with (
            patch.object(copy_to_clipboard.platform, "system", return_value="Darwin"),
            patch.object(copy_to_clipboard.subprocess, "run") as run,
        ):
            result, stdout, stderr = self.run_main(stdin="hello; rm -rf /\n")
        self.assertEqual(result, 0)
        run.assert_called_once_with(
            ["pbcopy"], input="hello; rm -rf /\n", text=True, check=True
        )
        self.assertIn("Copied text", stdout)
        self.assertEqual(stderr, "")

    def test_copies_utf8_file(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as file:
            file.write("héllo\n")
            file.flush()
            with patch.object(
                copy_to_clipboard.platform, "system", return_value="Darwin"
            ), patch.object(copy_to_clipboard.subprocess, "run") as run:
                result, _, _ = self.run_main(args=("--file", file.name))
        self.assertEqual(result, 0)
        run.assert_called_once_with(
            ["pbcopy"], input="héllo\n", text=True, check=True
        )

    def test_reports_missing_pbcopy(self):
        with (
            patch.object(copy_to_clipboard.platform, "system", return_value="Darwin"),
            patch.object(
                copy_to_clipboard.subprocess,
                "run",
                side_effect=FileNotFoundError,
            ),
        ):
            result, _, stderr = self.run_main(stdin="text")
        self.assertEqual(result, 1)
        self.assertIn("pbcopy was not found", stderr)

    def test_reports_pbcopy_failure_without_clipboard_contents(self):
        with (
            patch.object(copy_to_clipboard.platform, "system", return_value="Darwin"),
            patch.object(
                copy_to_clipboard.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(1, ["pbcopy"]),
            ),
        ):
            result, stdout, stderr = self.run_main(stdin="sensitive text")
        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("exit code 1", stderr)
        self.assertNotIn("sensitive text", stderr)


if __name__ == "__main__":
    unittest.main()
