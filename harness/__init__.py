"""Harness — barebones LLM coding assistant."""

# Keep the version in a conventional assignment so release tooling can update it.
version = "0.9.0"
__version__ = version


def get_version() -> str:
    return __version__
