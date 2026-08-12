"""Small Markdown-to-terminal renderer using ANSI escape sequences."""

import os
import re
import sys
from typing import List, Optional

_RESET = "\033[0m"
_BOLD = "\033[1m"
_ITALIC = "\033[3m"
_DIM = "\033[2m"
# Use a consistent color hierarchy so Markdown heading levels are easy to
# distinguish at a glance while remaining readable on dark terminals.
_HEADING_COLORS = {
    1: "\033[1;97m",  # bright white
    2: "\033[1;36m",  # cyan
    3: "\033[1;34m",  # blue
    4: "\033[1;35m",  # magenta
    5: "\033[1;33m",  # yellow
    6: "\033[1;32m",  # green
}
_INLINE_CODE = "\033[30;43m"
_CODE = "\033[38;5;252;48;5;236m"
_QUOTE = "\033[2;37m"
_BULLET = "\033[36m"

_FENCE_RE = re.compile(r"^\s*(```+|~~~+)(.*)$")
_HEADING_RE = re.compile(r"^(\s{0,3})(#{1,6})\s+(.*)$")
_LIST_RE = re.compile(r"^(\s*)([-*+] |\d+[.)] )(.*)$")


def colors_enabled() -> bool:
    """Return whether styling should be emitted for the current output."""
    if os.environ.get("HARNESS_NO_COLOR", "").lower() in {"1", "true", "yes", "on"}:
        return False
    if os.environ.get("HARNESS_COLOR", "").lower() in {"1", "true", "yes", "on", "always"}:
        return True
    return sys.stdout.isatty()


def _inline(text: str, color: bool) -> str:
    """Format common inline Markdown without touching escaped code spans."""
    if not color:
        return text

    parts: List[str] = []
    pos = 0
    # Code spans are split out first so their contents are never styled again.
    for match in re.finditer(r"(`+)(.+?)\1", text):
        parts.append(_inline_emphasis(text[pos:match.start()]))
        parts.append(f"{_INLINE_CODE}{match.group(2)}{_RESET}")
        pos = match.end()
    parts.append(_inline_emphasis(text[pos:]))
    return "".join(parts)


def _inline_emphasis(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: f"{_BOLD}{m.group(1) or m.group(2)}{_RESET}", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)|(?<!_)_([^_\n]+?)_(?!_)", lambda m: f"{_ITALIC}{m.group(1) or m.group(2)}{_RESET}", text)
    return text


def render_markdown(text: str, color: Optional[bool] = None) -> str:
    """Render common Markdown constructs for a terminal.

    This deliberately remains a small renderer, not a complete Markdown parser.
    Fenced code blocks are kept literal so source code and indentation survive.
    """
    if color is None:
        color = colors_enabled()

    output: List[str] = []
    in_code = False
    fence = ""
    for line in text.splitlines(keepends=True):
        ending = "\n" if line.endswith("\n") else ""
        body = line[:-1] if ending else line

        fence_match = _FENCE_RE.match(body)
        if fence_match:
            marker = fence_match.group(1)
            if not in_code:
                in_code = True
                fence = marker[0]
                language = fence_match.group(2).strip()
                label = f" {language}" if language else ""
                rendered = f"{_DIM}┌─ code{label} ─┐{_RESET}" if color else f"┌─ code{label} ─┐"
                output.append(rendered + ending)
            elif marker[0] == fence:
                in_code = False
                rendered = f"{_DIM}└{'─' * 12}┘{_RESET}" if color else f"└{'─' * 12}┘"
                output.append(rendered + ending)
            else:
                output.append(line)
            continue

        if in_code:
            output.append((f"{_CODE}{body}{_RESET}" if color else body) + ending)
            continue

        match = _HEADING_RE.match(body)
        if match:
            level = len(match.group(2))
            heading = f"{match.group(2)} {match.group(3)}"
            style = _HEADING_COLORS[level]
            output.append((f"{style}{heading}{_RESET}" if color else heading) + ending)
            continue

        match = _LIST_RE.match(body)
        if match:
            indent, marker, item = match.groups()
            bullet = f"{_BULLET}{marker}{_RESET}" if color else marker
            output.append(indent + bullet + _inline(item, color) + ending)
            continue

        if body.lstrip().startswith(">"):
            prefix, rest = body.split(">", 1)
            quote = f"{prefix}│{rest}"
            output.append((f"{_QUOTE}{quote}{_RESET}" if color else quote) + ending)
            continue

        if re.match(r"^\s*((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$", body):
            divider = "─" * 40
            output.append((f"{_DIM}{divider}{_RESET}" if color else divider) + ending)
            continue

        output.append(_inline(body, color) + ending)

    return "".join(output)
