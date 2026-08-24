import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import tools
from harness.registry import execute_tool, format_tool_result_content, get_full_system_prompt
from harness.skills import load_skill, parse_skill_references, skill_catalog


class ToolsTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.backup_dir = self.workspace / "backups"
        self.env_patcher = patch.dict(
            os.environ, {"HARNESS_BACKUP_DIR": str(self.backup_dir)}
        )
        self.env_patcher.start()
        self.patcher = patch("harness.tools.workspace_root", return_value=self.workspace)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.env_patcher.stop()
        self.temp_dir.cleanup()

    def test_system_prompt_loads_workspace_agents_instructions(self):
        (self.workspace / "AGENTS.md").write_text("Use the develop release flow.", encoding="utf-8")
        prompt = get_full_system_prompt(self.workspace)
        self.assertIn("Workspace instructions", prompt)
        self.assertIn("Use the develop release flow.", prompt)

    def test_system_prompt_ignores_missing_agents_file(self):
        self.assertEqual(get_full_system_prompt(self.workspace), get_full_system_prompt())

    def test_skill_references_are_parsed_without_loading_contents(self):
        references = parse_skill_references(
            "[Testing](.harness/skills/testing.md) [External](https://example.com/a.md) "
            "[Testing again](.harness/skills/testing.md#section)"
        )
        self.assertEqual([(item.name, item.path) for item in references], [
            ("Testing", ".harness/skills/testing.md"),
        ])

    def test_system_prompt_contains_skill_catalog_not_skill_contents(self):
        (self.workspace / "AGENTS.md").write_text(
            "Use skills: [Testing](skills/testing.md)", encoding="utf-8"
        )
        skills = self.workspace / "skills"
        skills.mkdir()
        (skills / "testing.md").write_text("secret testing instructions", encoding="utf-8")
        prompt = get_full_system_prompt(self.workspace)
        self.assertIn("Testing: skills/testing.md", prompt)
        self.assertNotIn("secret testing instructions", prompt)

    def test_load_skill_requires_active_reference_and_loads_by_name(self):
        (self.workspace / "AGENTS.md").write_text(
            "[Testing](skills/testing.md)", encoding="utf-8"
        )
        skills = self.workspace / "skills"
        skills.mkdir()
        (skills / "testing.md").write_text("run the tests", encoding="utf-8")
        result = load_skill("Testing", self.workspace)
        self.assertEqual(result["content"], "run the tests")
        self.assertIn("run the tests", format_tool_result_content("load_skill", result))
        self.assertIn("Missing required", execute_tool("load_skill", {}).get("error", ""))
        self.assertIn("not declared", load_skill("Other", self.workspace)["error"])

    def test_load_skill_rejects_external_symlink(self):
        outside = Path(tempfile.mkdtemp())
        try:
            (outside / "secret.md").write_text("secret", encoding="utf-8")
            skills = self.workspace / "skills"
            skills.mkdir()
            (skills / "secret.md").symlink_to(outside / "secret.md")
            (self.workspace / "AGENTS.md").write_text(
                "[Secret](skills/secret.md)", encoding="utf-8"
            )
            result = load_skill("Secret", self.workspace)
            self.assertIn("escapes", result["error"])
        finally:
            (outside / "secret.md").unlink()
            outside.rmdir()

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

    def test_run_command_uses_workspace_and_captures_result(self):
        result = tools.run_command("python -c \"print('ok')\"")
        self.assertTrue(result["passed"])
        self.assertEqual(result["returncode"], 0)
        self.assertIn("ok", result["stdout"])

    def test_git_status_and_diff_are_native_and_workspace_scoped(self):
        tools.run_command("git init -q && git config user.email test@example.com && git config user.name Test")
        path = self.workspace / "tracked.txt"
        path.write_text("before\n", encoding="utf-8")
        tools.run_command("git add tracked.txt && git commit -qm initial")
        path.write_text("after\n", encoding="utf-8")
        status = tools.git_status()
        self.assertTrue(status["passed"])
        self.assertIn("tracked.txt", status["stdout"])
        diff = tools.git_diff(path="tracked.txt")
        self.assertTrue(diff["passed"])
        self.assertIn("+after", diff["stdout"])

    def test_git_diff_reads_staged_changes_and_filters_by_path(self):
        tools.run_command("git init -q && git config user.email test@example.com && git config user.name Test")
        staged = self.workspace / "staged.txt"
        unstaged = self.workspace / "unstaged.txt"
        staged.write_text("before\n", encoding="utf-8")
        unstaged.write_text("before\n", encoding="utf-8")
        tools.run_command("git add staged.txt unstaged.txt && git commit -qm initial")
        staged.write_text("staged change\n", encoding="utf-8")
        unstaged.write_text("unstaged change\n", encoding="utf-8")
        tools.run_command("git add staged.txt")

        result = tools.git_diff(staged=True)
        self.assertTrue(result["passed"])
        self.assertIn("staged change", result["stdout"])
        self.assertNotIn("unstaged change", result["stdout"])

        result = tools.git_diff(staged=True, path="staged.txt")
        self.assertTrue(result["passed"])
        self.assertIn("staged change", result["stdout"])

        result = tools.git_diff(staged=True, path="unstaged.txt")
        self.assertTrue(result["passed"])
        self.assertEqual(result["stdout"], "")

    def test_git_diff_limits_changed_lines_per_file(self):
        diff = """diff --git a/one.txt b/one.txt
--- a/one.txt
+++ b/one.txt
@@ -1,4 +1,4 @@
-old 1
+new 1
-old 2
+new 2
diff --git a/two.txt b/two.txt
--- a/two.txt
+++ b/two.txt
@@ -1,2 +1,2 @@
-old
+new
"""
        limited, truncated = tools._limit_diff_per_file(diff, 2)
        self.assertTrue(truncated)
        self.assertEqual(limited.count("+new"), 2)
        self.assertIn("maximum 2 changed lines per file", limited)

    def test_git_diff_rejects_invalid_change_limit(self):
        self.assertIn("between 1 and 1000", tools.git_diff(max_changes_per_file=0)["error"])

    def test_git_diff_reports_empty_staged_diff(self):
        tools.run_command("git init -q && git config user.email test@example.com && git config user.name Test")
        path = self.workspace / "tracked.txt"
        path.write_text("content\n", encoding="utf-8")
        tools.run_command("git add tracked.txt && git commit -qm initial")

        result = tools.git_diff(staged=True)
        self.assertTrue(result["passed"])
        self.assertEqual(result["stdout"], "")

    def test_git_log_and_branch_list_are_read_only_native_tools(self):
        tools.run_command("git init -q && git config user.email test@example.com && git config user.name Test")
        path = self.workspace / "tracked.txt"
        path.write_text("initial\n", encoding="utf-8")
        tools.run_command("git add tracked.txt && git commit -qm initial")
        log = tools.git_log(limit=1)
        self.assertTrue(log["passed"])
        self.assertIn("initial", log["stdout"])
        branches = tools.git_branch_list()
        self.assertTrue(branches["passed"])
        self.assertIn("*", branches["stdout"])

    def test_git_read_only_tools_reject_invalid_arguments(self):
        self.assertIn("positive", tools.git_log(limit=0)["error"])
        self.assertIn("escapes", tools.git_diff(path="../outside.txt")["error"])

    def test_registry_dispatches_read_only_git_tools(self):
        tools.run_command("git init -q && git config user.email test@example.com && git config user.name Test")
        (self.workspace / "tracked.txt").write_text("initial\n", encoding="utf-8")
        tools.run_command("git add tracked.txt && git commit -qm initial")
        for name in ("git_status", "git_branch_list"):
            self.assertIn("passed", execute_tool(name, {}))
        self.assertIn("passed", execute_tool("git_log", {"limit": 1}))

    def test_run_command_rejects_invalid_timeout(self):
        result = tools.run_command("echo ok", timeout=0)
        self.assertIn("error", result)

    def test_read_file_returns_bounded_window_and_pagination(self):
        (self.workspace / "example.txt").write_text(
            "".join(f"line {number}\n" for number in range(1, 6)), encoding="utf-8"
        )
        result = tools.read_file("example.txt", start_line=2, max_lines=2)
        self.assertEqual(result["content"], "line 2\nline 3\n")
        self.assertEqual(result["start_line"], 2)
        self.assertEqual(result["end_line"], 3)
        self.assertEqual(result["lines_read"], 2)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["next_start_line"], 4)

    def test_read_file_rejects_invalid_pagination(self):
        (self.workspace / "example.txt").write_text("hello", encoding="utf-8")
        self.assertIn("positive", tools.read_file("example.txt", start_line=0)["error"])
        self.assertIn("between", tools.read_file("example.txt", max_lines=1001)["error"])

    def test_read_image_returns_inline_data_url(self):
        image = self.workspace / "pixel.png"
        image.write_bytes(b"fake-png")
        result = tools.read_image("pixel.png")
        self.assertEqual(result["mime_type"], "image/png")
        self.assertTrue(result["image_url"].startswith("data:image/png;base64,"))
        self.assertIn("pixel.png", result["file_path"])

    def test_read_image_rejects_non_image_and_missing_required_argument(self):
        (self.workspace / "notes.txt").write_text("not an image", encoding="utf-8")
        self.assertIn("Unsupported image", tools.read_image("notes.txt")["error"])
        self.assertIn("Missing required", execute_tool("read_image", {})["error"])

    def test_registry_formats_read_image_without_exposing_payload(self):
        image = self.workspace / "pixel.png"
        image.write_bytes(b"fake-png")
        result = execute_tool("read_image", {"filename": "pixel.png"})
        formatted = format_tool_result_content("read_image", result)
        self.assertIn("Image attached", formatted)
        self.assertNotIn("base64", formatted)

    def test_read_file_returns_content(self):
        (self.workspace / "example.txt").write_text("hello", encoding="utf-8")
        result = tools.read_file("example.txt")
        self.assertEqual(result["content"], "hello")
        self.assertFalse(result["has_more"])

    def test_search_files_honors_gitignore_and_limits_results(self):
        (self.workspace / ".gitignore").write_text("ignored.txt\nignored_dir/\n", encoding="utf-8")
        (self.workspace / "keep.py").write_text("needle\nneedle\n", encoding="utf-8")
        (self.workspace / "ignored.txt").write_text("needle\n", encoding="utf-8")
        ignored_dir = self.workspace / "ignored_dir"
        ignored_dir.mkdir()
        (ignored_dir / "file.py").write_text("needle\n", encoding="utf-8")

        result = tools.search_files("NEEDLE", glob="*.py", max_results=1)

        self.assertEqual(len(result["matches"]), 1)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["matches"][0]["file"], "keep.py")

    def test_search_files_rejects_workspace_escape(self):
        result = tools.search_files("needle", "../")
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
