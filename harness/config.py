"""Configuration for the active OpenAI-compatible backend."""

import getpass
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_CHAT_URL = f"{OPENROUTER_BASE_URL}/chat/completions"
OPENROUTER_MODELS_URL = f"{OPENROUTER_BASE_URL}/models"
OPENROUTER_MODEL = "openai/gpt-5.6-luna"
REQUEST_TIMEOUT_S = 600
DEFAULT_AUTH_MODE = "bearer"
DEFAULT_BACKEND_NAME = "OpenRouter"


@dataclass(frozen=True)
class BackendConfig:
    name: str
    base_url: str
    chat_url: str
    models_url: str
    model: str
    api_key: str
    auth_mode: str
    timeout_s: int
    reasoning_effort: Optional[str]

    @property
    def display_name(self) -> str:
        return self.name

    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.auth_mode == "bearer":
            if not self.api_key:
                raise RuntimeError(
                    f"{self.name} requires HARNESS_API_KEY when HARNESS_AUTH_MODE=bearer."
                )
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
MODEL_METADATA_TIMEOUT_S = 3
CONTEXT_COMPACTION_RATIO = 0.25
CONTEXT_COMPACTION_CAP = 200_000


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key:
                values[key] = val
    except OSError:
        pass
    return values


def global_config_path() -> Path:
    return Path(os.environ.get("HARNESS_CONFIG_FILE", "~/.harness/config.env")).expanduser()


def _try_load_dotenv() -> None:
    """Load least-specific config first; shell variables always win."""
    candidates = [global_config_path(), Path.cwd() / ".env", workspace_config_path()]
    shell_keys = set(os.environ)
    for path in candidates:
        for key, value in _read_dotenv(path).items():
            if key in shell_keys:
                continue
            os.environ[key] = value
            if key == "HARNESS_MODEL" and "OPENROUTER_MODEL" not in shell_keys:
                os.environ["OPENROUTER_MODEL"] = value


def backend_config() -> BackendConfig:
    """Resolve generic settings, falling back to the legacy OpenRouter preset."""
    base_url = os.environ.get("HARNESS_BASE_URL", OPENROUTER_BASE_URL).strip().rstrip("/")
    chat_url = os.environ.get("HARNESS_CHAT_URL", "").strip() or f"{base_url}/chat/completions"
    models_url = os.environ.get("HARNESS_MODELS_URL", "").strip() or f"{base_url}/models"
    model = os.environ.get("HARNESS_MODEL", "").strip()
    if not model:
        model = os.environ.get("OPENROUTER_MODEL", OPENROUTER_MODEL).strip() or OPENROUTER_MODEL
    api_key = os.environ.get("HARNESS_API_KEY", "").strip()
    if not api_key:
        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    auth_mode = os.environ.get("HARNESS_AUTH_MODE", DEFAULT_AUTH_MODE).strip().lower() or DEFAULT_AUTH_MODE
    if auth_mode not in {"none", "bearer"}:
        raise ValueError("HARNESS_AUTH_MODE must be one of: none, bearer")
    try:
        timeout_s = int(os.environ.get("HARNESS_REQUEST_TIMEOUT_S", REQUEST_TIMEOUT_S))
    except ValueError as exc:
        raise ValueError("HARNESS_REQUEST_TIMEOUT_S must be an integer") from exc
    return BackendConfig(
        name=os.environ.get("HARNESS_BACKEND_NAME", DEFAULT_BACKEND_NAME).strip() or DEFAULT_BACKEND_NAME,
        base_url=base_url,
        chat_url=chat_url,
        models_url=models_url,
        model=model,
        api_key=api_key,
        auth_mode=auth_mode,
        timeout_s=timeout_s,
        reasoning_effort=os.environ.get("HARNESS_REASONING_EFFORT", "").strip() or None,
    )


def _save_config(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    values = _read_dotenv(path)
    values[key] = value
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def configure() -> bool:
    """Interactively collect and save an API key. Return whether it succeeded."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Harness needs an interactive terminal to configure an API key.", file=sys.stderr)
        return False
    print("OpenRouter API key not found.")
    try:
        value = getpass.getpass("Paste your OpenRouter API key (input hidden): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not value:
        print("No API key entered.", file=sys.stderr)
        return False
    print("Save key globally or for this project? [global/project/none]", end=" ")
    try:
        choice = input().strip().lower() or "global"
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if choice == "global":
        path = global_config_path()
    elif choice == "project":
        path = Path.cwd() / ".env"
    else:
        os.environ["OPENROUTER_API_KEY"] = value
        return True
    _save_config(path, "OPENROUTER_API_KEY", value)
    os.environ["OPENROUTER_API_KEY"] = value
    print(f"Saved configuration to {path}")
    return True


def workspace_root() -> Path:
    raw = os.environ.get("HARNESS_WORKSPACE", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd().resolve()


def get_model() -> str:
    return backend_config().model


def workspace_config_path() -> Path:
    """Return the workspace-scoped config file inside the workspace .harness directory."""
    return workspace_root() / ".harness" / "config.env"


def save_workspace_model(model: str) -> Path:
    """Persist a model id as the workspace default.

    Future Harness launches in this workspace start on this model unless
    OPENROUTER_MODEL is set in the shell environment, which still wins.
    """
    value = model.strip()
    if not value:
        raise ValueError("model id cannot be empty")
    path = workspace_config_path()
    _save_config(path, "HARNESS_MODEL", value)
    os.environ["OPENROUTER_MODEL"] = value
    return path


def workspace_model() -> str:
    """Return the model saved for this workspace, or an empty string if none."""
    values = _read_dotenv(workspace_config_path())
    return values.get("HARNESS_MODEL", values.get("OPENROUTER_MODEL", ""))


def set_model(model: str) -> None:
    """Select a model for the current Harness process."""
    value = model.strip()
    if not value:
        raise ValueError("model id cannot be empty")
    os.environ["HARNESS_MODEL"] = value


def history_file_path() -> Path:
    custom = os.environ.get("HARNESS_HISTORY_FILE")
    if custom:
        return Path(custom).expanduser()
    d = Path(os.environ.get("HARNESS_LOGS_DIR", Path.home() / "harness_logs")).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return d / f"coding_agent_history_{stamp}.txt"


def auto_approve() -> bool:
    return os.environ.get("HARNESS_AUTO_APPROVE", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def dry_run() -> bool:
    return os.environ.get("HARNESS_DRY_RUN", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def init() -> None:
    _try_load_dotenv()
    active = backend_config()
    if active.auth_mode == "bearer" and not active.api_key:
        if not os.environ.get("HARNESS_API_KEY", "").strip() and os.environ.get("OPENROUTER_API_KEY", "").strip():
            os.environ["HARNESS_API_KEY"] = os.environ["OPENROUTER_API_KEY"]
            active = backend_config()
        elif sys.stdin.isatty() and sys.stdout.isatty():
            if not configure():
                raise RuntimeError("An API key is required when HARNESS_AUTH_MODE=bearer.")
            os.environ["HARNESS_API_KEY"] = os.environ.get("OPENROUTER_API_KEY", "")
            active = backend_config()
        else:
            raise RuntimeError(
                "No API key is configured for bearer authentication. Set HARNESS_API_KEY "
                "or the legacy OPENROUTER_API_KEY, or use HARNESS_AUTH_MODE=none."
            )
    logging.basicConfig(
        level=getattr(logging, os.environ.get("HARNESS_LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info("workspace: %s model: %s", workspace_root(), get_model())
