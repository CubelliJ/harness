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

    def test_run_command_rejects_invalid_timeout(self):
        result = tools.run_command("echo ok", timeout=0)
        self.assertIn("error", result)

    def test_read_file_returns_content(self):
        (self.workspace / "example.txt").write_text("hello", encoding="utf-8")
        result = tools.read_file("example.txt")
        self.assertEqual(result["content"], "hello")

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
