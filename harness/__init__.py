"""Harness — barebones LLM coding assistant."""

from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
import re


def _version() -> str:
    """Read the authoritative version from installed metadata or pyproject.toml."""
    try:
        return package_version("harness-cli")
    except PackageNotFoundError:
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        match = re.search(
            r'^version\s*=\s*["\']([^"\']+)["\']\s*$',
            pyproject.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        if match:
            return match.group(1)
        raise RuntimeError("Unable to determine Harness version")


__version__ = _version()


def get_version() -> str:
    return __version__
