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
    text = re.sub(
        r"(?<!\*)\*([^*\n]+?)\*(?!\*)|(?<![\w_])_([^_\n]+?)_(?![\w_])",
        lambda m: f"{_ITALIC}{m.group(1) or m.group(2)}{_RESET}",
        text,
    )
    return text


class MarkdownStreamRenderer:
    """Render Markdown incrementally while retaining ambiguous fragments.

    A complete line is still the safest unit for block Markdown.  For a
    partial line, however, delaying ordinary prose makes streamed responses
    appear frozen.  We therefore emit partial text unless it could still
    become a heading, list, fence, code span, or emphasis span.  Ambiguous
    fragments are kept intact so styling is never split across two writes.
    """

    def __init__(self, color: Optional[bool] = None) -> None:
        self.color = colors_enabled() if color is None else color
        self._pending = ""
        self._in_code = False
        self._fence = ""

    @staticmethod
    def _has_incomplete_inline(text: str) -> bool:
        """Return whether *text* ends with Markdown needing more input."""
        # An unfinished code span is unambiguously unsafe to render yet.
        backticks = re.findall(r"(?<!\\)`+", text)
        if len(backticks) % 2:
            return True

        # Ignore escaped punctuation and code spans while looking for emphasis.
        plain = re.sub(r"(?<!\\)`+[^`\n]*`+", "", text)
        plain = re.sub(r"\\([*_`])", "", plain)
        if plain.count("**") % 2 or plain.count("__") % 2:
            return True
        # A single delimiter is considered incomplete only when it starts a
        # word/span at the end of the fragment; this avoids buffering prose
        # such as "2 * 3".
        if re.search(r"\d\s+\*$", plain):
            return True
        if re.search(r"(?<![\*])\*\S[^*\n]*$|(?<![\*])\*$", plain):
            return True
        if re.search(r"(?<![\w_])_[^_\n]*$|(?<![\w_])_$", plain):
            return True
        # An underscore that appears to close emphasis may instead be part of
        # an identifier (``_name_next``). Wait for the following character so
        # the word-boundary rule in _inline_emphasis can decide correctly.
        if re.search(r"\w_$", plain):
            return True
        return False

    def _incomplete_inline_start(self, text: str) -> Optional[int]:
        """Return the first delimiter that may need more input."""
        if re.search(r"\d\s+\*$", text):
            return None
        if not self._has_incomplete_inline(text):
            return None
        candidates = []
        for marker in ("**", "__", "*", "_"):
            index = text.find(marker)
            if index >= 0 and not (index and text[index - 1] == "\\"):
                candidates.append(index)
        return min(candidates) if candidates else 0

    def _partial_is_block(self, text: str) -> bool:
        """Whether a partial line must be retained for block rendering."""
        if self._in_code:
            # Code content must stay together until its newline. Flushing a
            # partial code line through _inline() loses the code styling and
            # leaves an empty styled line when the newline arrives.
            return True
        return bool(
            _FENCE_RE.match(text)
            or re.match(r"^\s*(```*|~~~*)$", text)
            or re.match(r"^\s{0,3}#{1,6}(?:\s+.*)?$", text)
            or re.match(r"^\s*(?:[-*+]\s*|\d+[.)]\s*)", text)
            or re.match(r"^\s*\d+(?:\s+)?$", text)
            or re.match(r"^\s*\d+\s+\*", text)
            or text.lstrip().startswith(">")
            or re.match(r"^\s*(?:[-*_]\s*){1,3}$", text)
        )

    def _partial_is_ambiguous(self, text: str) -> bool:
        """Whether a no-newline fragment must remain buffered."""
        # Check block prefixes first: a lone ``#`` or ``*`` may be the start
        # of a heading/list, not an inline delimiter to flush.
        return self._partial_is_block(text) or self._has_incomplete_inline(text)

    def _render_line(self, line: str) -> str:
        ending = "\n" if line.endswith("\n") else ""
        body = line[:-1] if ending else line
        if body.endswith("\r"):
            body = body[:-1]
        match = _FENCE_RE.match(body)
        if match:
            marker = match.group(1)
            if not self._in_code:
                self._in_code = True
                self._fence = marker[0]
                label = f" {match.group(2).strip()}" if match.group(2).strip() else ""
                rendered = f"{_DIM}┌─ code{label} ─┐{_RESET}" if self.color else f"┌─ code{label} ─┐"
            elif marker[0] == self._fence:
                self._in_code = False
                rendered = f"{_DIM}└{'─' * 12}┘{_RESET}" if self.color else f"└{'─' * 12}┘"
            else:
                rendered = body
            return rendered + ending
        if self._in_code:
            return (f"{_CODE}{body}{_RESET}" if self.color else body) + ending
        return render_markdown(body + ending, color=self.color)

    def feed(self, text: str) -> str:
        self._pending += text
        lines = self._pending.splitlines(keepends=True)
        self._pending = ""
        if lines and not lines[-1].endswith(("\n", "\r")):
            self._pending = lines.pop()

        rendered = "".join(self._render_line(line) for line in lines)
        if self._pending:
            if self._partial_is_ambiguous(self._pending):
                # Block syntax must remain whole; otherwise a heading or list
                # can be written literally before its newline arrives.
                start = None if self._partial_is_block(self._pending) else self._incomplete_inline_start(self._pending)
                if start is not None and start > 0:
                    rendered += _inline(self._pending[:start], self.color)
                    self._pending = self._pending[start:]
            else:
                fragment, self._pending = self._pending, ""
                rendered += _inline(fragment, self.color)
        return rendered

    def finish(self) -> str:
        if not self._pending:
            return ""
        pending, self._pending = self._pending, ""
        return self._render_line(pending)


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
