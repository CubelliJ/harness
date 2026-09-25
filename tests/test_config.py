"""Tests for workspace-level default model persistence."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import config


class BackendConfigTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_defaults_to_preferred_model_when_catalogue_lists_it(self):
        body = {"data": [{"id": "openai/gpt-6-luna"}, {"id": "openai/gpt-5.6-luna"}]}
        config._resolved_default_models.clear()
        with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(body).encode())):
            self.assertEqual(config.backend_config().model, "openai/gpt-6-luna")

    def test_defaults_to_fallback_when_preferred_model_is_unavailable(self):
        body = {"data": [{"id": "openai/gpt-5.6-luna"}]}
        config._resolved_default_models.clear()
        with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(body).encode())):
            self.assertEqual(config.backend_config().model, "openai/gpt-5.6-luna")

    def test_model_catalogue_failure_uses_preferred_default(self):
        config._resolved_default_models.clear()
        with patch("urllib.request.urlopen", side_effect=OSError("offline")):
            self.assertEqual(config.backend_config().model, "openai/gpt-6-luna")

    def test_safety_model_defaults_to_resolved_model_and_accepts_override(self):
        body = {"data": [{"id": "openai/gpt-5.6-luna"}]}
        config._resolved_default_models.clear()
        with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(body).encode())):
            self.assertEqual(config.safety_model(), "openai/gpt-5.6-luna")
        os.environ["HARNESS_SAFETY_MODEL"] = "custom/safety"
        self.assertEqual(config.safety_model(), "custom/safety")

    def test_generic_urls_are_derived_and_trailing_slash_is_removed(self):
        os.environ.update({
            "HARNESS_BASE_URL": "https://gateway.example.com/v1///",
            "HARNESS_MODEL": "example-model",
            "HARNESS_AUTH_MODE": "none",
        })
        active = config.backend_config()
        self.assertEqual(active.base_url, "https://gateway.example.com/v1")
        self.assertEqual(active.chat_url, "https://gateway.example.com/v1/chat/completions")
        self.assertEqual(active.models_url, "https://gateway.example.com/v1/models")

    def test_explicit_urls_and_generic_values_override_legacy_values(self):
        os.environ.update({
            "HARNESS_BASE_URL": "https://gateway.example.com/v1",
            "HARNESS_CHAT_URL": "https://gateway.example.com/chat",
            "HARNESS_MODELS_URL": "https://gateway.example.com/models",
            "HARNESS_API_KEY": "generic-key",
            "HARNESS_MODEL": "example-model",
            "HARNESS_AUTH_MODE": "bearer",
            "HARNESS_BACKEND_NAME": "Example Gateway",
            "OPENROUTER_API_KEY": "legacy-key",
            "OPENROUTER_MODEL": "legacy-model",
        })
        active = config.backend_config()
        self.assertEqual(active.chat_url, "https://gateway.example.com/chat")
        self.assertEqual(active.models_url, "https://gateway.example.com/models")
        self.assertEqual(active.api_key, "generic-key")
        self.assertEqual(active.model, "example-model")
        self.assertEqual(active.name, "Example Gateway")

    def test_auth_headers_support_none_and_bearer(self):
        os.environ.update({"HARNESS_AUTH_MODE": "none", "HARNESS_API_KEY": "secret"})
        self.assertNotIn("Authorization", config.backend_config().headers())
        os.environ["HARNESS_AUTH_MODE"] = "bearer"
        self.assertEqual(config.backend_config().headers()["Authorization"], "Bearer secret")

    def test_cost_rates_are_loaded_and_reject_invalid_values(self):
        os.environ.update({
            "HARNESS_AUTH_MODE": "none",
            "HARNESS_INPUT_COST_PER_MILLION": "1.25",
            "HARNESS_CACHE_READ_COST_PER_MILLION": "0.12",
            "HARNESS_CACHE_WRITE_COST_PER_MILLION": "0.3",
            "HARNESS_OUTPUT_COST_PER_MILLION": "4",
        })
        active = config.backend_config()
        self.assertEqual(active.input_cost_per_million, 1.25)
        self.assertEqual(active.cache_read_cost_per_million, 0.12)
        self.assertEqual(active.cache_write_cost_per_million, 0.3)
        self.assertEqual(active.output_cost_per_million, 4.0)
        os.environ["HARNESS_OUTPUT_COST_PER_MILLION"] = "-1"
        with self.assertRaisesRegex(ValueError, "non-negative"):
            config.backend_config()

    def test_bearer_without_key_fails_clearly(self):
        os.environ["HARNESS_AUTH_MODE"] = "bearer"
        with self.assertRaisesRegex(RuntimeError, "HARNESS_API_KEY"):
            config.backend_config().headers()

    def test_machine_then_workspace_config_precedence(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as workspace:
            machine = Path(home) / ".harness" / "config.env"
            machine.parent.mkdir()
            machine.write_text("HARNESS_BACKEND_NAME=Machine\nHARNESS_MODEL=machine-model\n")
            workspace_file = Path(workspace) / ".harness" / "config.env"
            workspace_file.parent.mkdir()
            workspace_file.write_text("HARNESS_MODEL=workspace-model\n")
            os.environ.update({"HOME": home, "HARNESS_WORKSPACE": workspace})
            config._try_load_dotenv()
            self.assertEqual(os.environ["HARNESS_BACKEND_NAME"], "Machine")
            self.assertEqual(config.get_model(), "workspace-model")


class WorkspaceModelTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workspace = Path(tmp.name)
        env_patcher = patch.dict(os.environ, {"HARNESS_WORKSPACE": str(self.workspace)})
        env_patcher.start()
        os.environ.pop("HARNESS_MODEL", None)
        os.environ.pop("OPENROUTER_MODEL", None)
        self.addCleanup(env_patcher.stop)

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