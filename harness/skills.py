"""Lazy loading of skills explicitly linked from a workspace AGENTS.md."""

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlparse

from harness.config import workspace_root

MAX_SKILL_BYTES = 256 * 1024
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


@dataclass(frozen=True)
class SkillReference:
    """A skill declared by a Markdown link in AGENTS.md."""

    name: str
    path: str


def parse_skill_references(agents_content: str) -> List[SkillReference]:
    """Extract unique relative Markdown-file links from AGENTS.md."""
    references: List[SkillReference] = []
    seen = set()
    for match in _MARKDOWN_LINK_RE.finditer(agents_content):
        name = " ".join(match.group(1).split())
        target = match.group(2).strip().split(None, 1)[0].strip("<>")
        parsed = urlparse(target)
        if not name or parsed.scheme or parsed.netloc or not target:
            continue
        path = target.split("#", 1)[0].split("?", 1)[0]
        if not path.lower().endswith(".md"):
            continue
        normalized = Path(path).as_posix()
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        references.append(SkillReference(name=name, path=normalized))
    return references


def _agents_content(workspace: Path) -> str:
    try:
        return (workspace / "AGENTS.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def skill_references(workspace: Path = None) -> List[SkillReference]:
    """Return skills declared in the workspace AGENTS.md."""
    root = (workspace or workspace_root()).expanduser().resolve()
    return parse_skill_references(_agents_content(root))


def _resolve_skill_path(root: Path, path: str) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve(strict=False)
    else:
        resolved = (root / candidate).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Skill path escapes the configured workspace") from exc
    return resolved


def skill_catalog(workspace: Path = None) -> str:
    """Return a compact prompt section without loading skill contents."""
    references = skill_references(workspace)
    if not references:
        return ""
    root = (workspace or workspace_root()).expanduser().resolve()
    lines = [
        "Workspace skills are available through the load_skill tool. "
        "Load a relevant skill before relying on its instructions:",
    ]
    for reference in references:
        try:
            path = _resolve_skill_path(root, reference.path)
            status = "" if path.is_file() else " [missing]"
        except ValueError:
            status = " [invalid path]"
        lines.append(f"- {reference.name}: {reference.path}{status}")
    return "\n".join(lines)


def load_skill(skill: str, workspace: Path = None) -> Dict[str, str]:
    """Load an explicitly declared skill by name or path."""
    if not isinstance(skill, str) or not skill.strip():
        return {"error": "skill cannot be empty"}
    root = (workspace or workspace_root()).expanduser().resolve()
    references = skill_references(root)
    requested = skill.strip().casefold()
    reference = next(
        (item for item in references
         if item.name.casefold() == requested or item.path.casefold() == requested),
        None,
    )
    if reference is None:
        return {"error": f"Skill is not declared in AGENTS.md: {skill}"}
    try:
        path = _resolve_skill_path(root, reference.path)
    except ValueError as exc:
        return {"error": str(exc)}
    if not path.is_file():
        return {"error": f"Skill file not found: {reference.path}"}
    try:
        if path.stat().st_size > MAX_SKILL_BYTES:
            return {"error": f"Skill file exceeds {MAX_SKILL_BYTES} bytes: {reference.path}"}
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return {"error": f"Could not read skill {reference.path}: {exc}"}
    return {"name": reference.name, "path": reference.path, "content": content}
