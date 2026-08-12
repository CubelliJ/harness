import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import tools


class ToolsTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.patcher = patch("harness.tools.workspace_root", return_value=self.workspace)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_resolve_abs_path_rejects_traversal(self):
        with self.assertRaises(ValueError):
            tools.resolve_abs_path("../outside.txt")

    def test_resolve_abs_path_rejects_symlink_outside_workspace(self):
        outside = Path(tempfile.mkdtemp())
        try:
            link = self.workspace / "outside-link"
            link.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                tools.resolve_abs_path("outside-link/file.txt")
        finally:
            outside.rmdir()

    def test_list_files_is_usable(self):
        (self.workspace / "b.txt").write_text("b", encoding="utf-8")
        (self.workspace / "a.txt").write_text("a", encoding="utf-8")
        result = tools.list_files(".")
        self.assertNotIn("error", result)
        self.assertEqual({item["filename"] for item in result["files"]}, {"a.txt", "b.txt"})

    def test_edit_preview_replaces_only_first_match(self):
        path = self.workspace / "example.txt"
        path.write_text("one\none\n", encoding="utf-8")
        result = tools.edit_preview("example.txt", "one", "two")
        self.assertEqual(result["action"], "edited")
        self.assertEqual(result["matches"], 2)
        self.assertEqual(result["proposed"], "two\none\n")
        self.assertIn("-one", result["diff"])
        self.assertIn("+two", result["diff"])
        self.assertEqual(path.read_text(encoding="utf-8"), "one\none\n")

    def test_edit_file_dry_run_does_not_change_file(self):
        path = self.workspace / "example.txt"
        path.write_text("before", encoding="utf-8")
        result = tools.edit_file("example.txt", "before", "after", apply=False)
        self.assertEqual(result["action"], "dry_run")
        self.assertEqual(path.read_text(encoding="utf-8"), "before")
        self.assertNotIn("original", result)
        self.assertNotIn("proposed", result)

    def test_edit_file_creates_file_and_backup_on_replacement(self):
        path = self.workspace / "example.txt"
        path.write_text("before", encoding="utf-8")
        result = tools.edit_file("example.txt", "before", "after")
        self.assertEqual(path.read_text(encoding="utf-8"), "after")
        self.assertTrue(Path(result["backup_path"]).is_file())
        self.assertEqual(Path(result["backup_path"]).read_text(encoding="utf-8"), "before")

    def test_edit_file_reports_missing_old_string(self):
        path = self.workspace / "example.txt"
        path.write_text("before", encoding="utf-8")
        result = tools.edit_file("example.txt", "missing", "after")
        self.assertEqual(result["action"], "old_str not found")
        self.assertEqual(path.read_text(encoding="utf-8"), "before")

    def test_read_file_returns_content(self):
        (self.workspace / "example.txt").write_text("hello", encoding="utf-8")
        result = tools.read_file("example.txt")
        self.assertEqual(result["content"], "hello")


if __name__ == "__main__":
    unittest.main()
