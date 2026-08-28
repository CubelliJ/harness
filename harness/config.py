"""Minimal config: OpenRouter + workspace."""

import getpass
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_MODEL = "openai/gpt-5.6-luna"
REQUEST_TIMEOUT_S = 600
MODEL_METADATA_TIMEOUT_S = 3
CONTEXT_COMPACTION_RATIO = 0.25
CONTEXT_COMPACTION_CAP = 250_000


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
    """Load global, project, then workspace config; shell variables always win."""
    # The source checkout .env remains useful during development, but an installed
    # Harness must never depend on the directory where its package was installed.
    candidates = [global_config_path(), Path.cwd() / ".env"]
    source_env = Path(__file__).resolve().parent.parent / ".env"
    if source_env != Path.cwd() / ".env":
        candidates.append(source_env)
    # Workspace config is most specific, so it overrides the generic .env files.
    candidates.append(workspace_config_path())
    for path in candidates:
        for key, value in _read_dotenv(path).items():
            os.environ.setdefault(key, value)


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
    return os.environ.get("OPENROUTER_MODEL", OPENROUTER_MODEL).strip() or OPENROUTER_MODEL


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
    _save_config(path, "OPENROUTER_MODEL", value)
    os.environ["OPENROUTER_MODEL"] = value
    return path


def workspace_model() -> str:
    """Return the model saved for this workspace, or an empty string if none."""
    return _read_dotenv(workspace_config_path()).get("OPENROUTER_MODEL", "")


def set_model(model: str) -> None:
    """Select a model for the current Harness process."""
    value = model.strip()
    if not value:
        raise ValueError("model id cannot be empty")
    os.environ["OPENROUTER_MODEL"] = value


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
    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        if sys.stdin.isatty() and sys.stdout.isatty():
            if not configure():
                raise RuntimeError("OPENROUTER_API_KEY is required to use Harness.")
        else:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not configured. Run `python -m harness configure` "
                "or set the environment variable."
            )
    logging.basicConfig(
        level=getattr(logging, os.environ.get("HARNESS_LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info("workspace: %s model: %s", workspace_root(), get_model())
