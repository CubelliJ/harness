#!/usr/bin/env python3
"""Validate Agent Skills in a workspace."""

from __future__ import annotations

import re
import sys
from pathlib import Path


NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_DESCRIPTION_LENGTH = 1024
MAX_COMPATIBILITY_LENGTH = 500


def parse_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("frontmatter must start with ---")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("frontmatter must end with ---")

    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        key, separator, value = line.partition(":")
        if not separator or not key.strip():
            raise ValueError(f"invalid frontmatter line: {line!r}")
        fields[key.strip()] = value.strip()
    return fields


def validate_skill(directory: Path) -> None:
    if not NAME_PATTERN.fullmatch(directory.name):
        raise ValueError("directory name must be lowercase kebab-case")

    skill_file = directory / "SKILL.md"
    if not skill_file.is_file():
        raise ValueError("missing SKILL.md")

    fields = parse_frontmatter(skill_file)
    name = fields.get("name", "")
    if name != directory.name:
        raise ValueError(f"frontmatter name {name!r} does not match directory")
    if not NAME_PATTERN.fullmatch(name) or len(name) > 64:
        raise ValueError("name must be lowercase kebab-case and at most 64 characters")

    description = fields.get("description", "")
    if not description or len(description) > MAX_DESCRIPTION_LENGTH:
        raise ValueError("description must be non-empty and at most 1024 characters")

    compatibility = fields.get("compatibility")
    if compatibility is not None and len(compatibility) > MAX_COMPATIBILITY_LENGTH:
        raise ValueError("compatibility must be at most 500 characters")


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) == 2 else Path(".harness/skills")
    if len(argv) > 2:
        print(f"usage: {argv[0]} [skills-directory]", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"error: skills directory not found: {root}", file=sys.stderr)
        return 1

    directories = sorted(path for path in root.iterdir() if path.is_dir())
    if not directories:
        print(f"error: no skill directories found in {root}", file=sys.stderr)
        return 1

    failures = 0
    for directory in directories:
        try:
            validate_skill(directory)
        except (OSError, ValueError) as exc:
            print(f"invalid: {directory}: {exc}", file=sys.stderr)
            failures += 1
        else:
            print(f"valid: {directory / 'SKILL.md'}")

    if failures:
        print(f"{failures} invalid skill(s)", file=sys.stderr)
        return 1
    print(f"validated {len(directories)} Agent Skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
