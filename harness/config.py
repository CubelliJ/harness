"""Minimal config: OpenRouter + workspace."""

import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "openai/gpt-5.6-luna"
REQUEST_TIMEOUT_S = 600


def _try_load_dotenv() -> None:
    path = Path.cwd() / ".env"
    if not path.is_file():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        pass


def workspace_root() -> Path:
    raw = os.environ.get("HARNESS_WORKSPACE", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd().resolve()


def get_model() -> str:
    return os.environ.get("OPENROUTER_MODEL", OPENROUTER_MODEL).strip() or OPENROUTER_MODEL


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
    logging.basicConfig(
        level=getattr(logging, os.environ.get("HARNESS_LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info("workspace: %s model: %s", workspace_root(), get_model())
