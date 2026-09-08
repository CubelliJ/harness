"""Lazy loading of skills explicitly linked from a workspace AGENTS.md."""

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from harness.config import workspace_root

MAX_SKILL_BYTES = 256 * 1024
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


@dataclass(frozen=True)
class SkillReference:
    """A skill declared by a Markdown link in AGENTS.md."""

    name: str
    path: str
    origin: str = "workspace"


@dataclass(frozen=True)
class SkillSource:
    """A discovered skill directory and its precedence origin."""

    name: str
    path: Path
    origin: str


_BUILTIN_SKILLS = Path(__file__).resolve().parent


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
        if Path(path).name != "SKILL.md":
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


def _user_skills_root() -> Path:
    return (Path.home() / ".harness" / "skills").expanduser().resolve()


def _directory_sources(root: Path, origin: str) -> List[SkillSource]:
    if not root.is_dir():
        return []
    sources = []
    for directory in sorted(root.iterdir()):
        skill_file = directory / "SKILL.md"
        if not directory.is_dir() or not skill_file.is_file():
            continue
        resolved_directory = directory.resolve(strict=False)
        resolved_file = skill_file.resolve(strict=False)
        try:
            resolved_directory.relative_to(root)
            resolved_file.relative_to(root)
        except ValueError:
            continue
        if resolved_file.name == "SKILL.md" and resolved_file.parent == resolved_directory:
            sources.append(SkillSource(directory.name, resolved_directory, origin))
    return sources


def skill_sources(workspace: Path = None) -> List[SkillSource]:
    """Discover workspace, user, and installed skills by precedence."""
    root = (workspace or workspace_root()).expanduser().resolve()
    sources = _directory_sources(root / ".harness" / "skills", "workspace")
    references = skill_references(root)
    for reference in references:
        try:
            path = _resolve_skill_path(root, reference.path)
        except ValueError:
            continue
        if path.name == "SKILL.md" and path.parent != root:
            sources.append(SkillSource(reference.name, path.parent, "workspace"))
    sources.extend(_directory_sources(_user_skills_root(), "user"))
    sources.extend(_directory_sources(_BUILTIN_SKILLS, "installation"))

    unique = []
    seen = set()
    for source in sources:
        key = source.name.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(source)
    return unique


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
    sources = skill_sources(workspace)
    if not sources:
        return ""
    lines = [
        "Skills are available through the load_skill tool. "
        "Load a relevant skill before relying on its instructions:",
    ]
    for source in sources:
        label = source.path / "SKILL.md"
        lines.append(f"- {source.name} [{source.origin}]: {label}")
    return "\n".join(lines)


def _skill_resources(path: Path) -> List[Dict[str, Any]]:
    """Return safe, inspectable files bundled alongside a skill."""
    resources = []
    try:
        candidates = sorted(item for item in path.rglob("*") if item.is_file())
    except OSError:
        return resources
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(path)
        except ValueError:
            continue
        resources.append({
            "path": str(resolved),
            "relative_path": resolved.relative_to(path).as_posix(),
        })
    return resources


def load_skill(skill: str, workspace: Path = None) -> Dict[str, Any]:
    """Load a skill and expose paths to files bundled alongside it."""
    if not isinstance(skill, str) or not skill.strip():
        return {"error": "skill cannot be empty"}
    root = (workspace or workspace_root()).expanduser().resolve()
    requested = skill.strip().casefold()
    workspace_reference = next(
        (item for item in skill_references(root)
         if item.name.casefold() == requested or item.path.casefold() == requested),
        None,
    )
    if workspace_reference is not None:
        try:
            workspace_path = _resolve_skill_path(root, workspace_reference.path)
        except ValueError as exc:
            return {"error": str(exc)}
        if workspace_path.name != "SKILL.md" or workspace_path.parent == root:
            return {"error": f"Skill path must point to a skill directory's SKILL.md: {workspace_reference.path}"}

    source = next(
        (item for item in skill_sources(root)
         if item.name.casefold() == requested or str(item.path).casefold() == requested),
        None,
    )
    if source is None:
        return {"error": f"Skill is not available in workspace, user, or installation skills: {skill}"}
    path = source.path / "SKILL.md"
    if not path.is_file():
        return {"error": f"Skill file not found: {path}"}
    try:
        if path.stat().st_size > MAX_SKILL_BYTES:
            return {"error": f"Skill file exceeds {MAX_SKILL_BYTES} bytes: {path}"}
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return {"error": f"Could not read skill {path}: {exc}"}
    return {
        "name": source.name,
        "path": str(path),
        "origin": source.origin,
        "content": content,
        "resources": _skill_resources(source.path),
    }
