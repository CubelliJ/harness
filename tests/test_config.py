"""Tests for workspace-level default model persistence."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import config


class WorkspaceModelTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workspace = Path(tmp.name)
        env_patcher = patch.dict(os.environ, {"HARNESS_WORKSPACE": str(self.workspace)})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        self.addCleanup(os.environ.pop, "OPENROUTER_MODEL", None)

    def test_workspace_config_path_is_under_harness_dir(self):
        path = config.workspace_config_path()
        self.assertEqual(
            path, (self.workspace / ".harness" / "config.env").resolve()
        )

    def test_workspace_model_empty_when_unsaved(self):
        self.assertEqual(config.workspace_model(), "")

    def test_save_workspace_model_writes_and_applies(self):
        path = config.save_workspace_model("z-ai/glm-4.6")
        self.assertEqual(config.workspace_model(), "z-ai/glm-4.6")
        self.assertEqual(os.environ["OPENROUTER_MODEL"], "z-ai/glm-4.6")
        self.assertEqual(config.get_model(), "z-ai/glm-4.6")
        self.assertTrue(path.exists())
        # Restricted permissions match the other saved config files.
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_save_workspace_model_rejects_empty(self):
        with self.assertRaises(ValueError):
            config.save_workspace_model("   ")

    def test_saved_workspace_model_loaded_by_try_load_dotenv(self):
        config.save_workspace_model("z-ai/glm-4.6")
        os.environ.pop("OPENROUTER_MODEL", None)
        config._try_load_dotenv()
        self.assertEqual(os.environ.get("OPENROUTER_MODEL"), "z-ai/glm-4.6")

    def test_shell_environment_wins_over_workspace_model(self):
        config.save_workspace_model("z-ai/glm-4.6")
        os.environ["OPENROUTER_MODEL"] = "anthropic/claude-sonnet-4.5"
        self.assertEqual(config.get_model(), "anthropic/claude-sonnet-4.5")


if __name__ == "__main__":
    unittest.main()