"""Session-only Agent and Plan mode state."""

from dataclasses import dataclass
from enum import Enum
from typing import Set


class SessionMode(str, Enum):
    AGENT = "agent"
    PLAN = "plan"


PLAN_ALLOWED_TOOLS: Set[str] = {
    "list_files",
    "read_file",
    "read_image",
    "search_files",
    "git_status",
    "git_diff",
    "git_log",
    "git_branch_list",
    "load_skill",
}


@dataclass
class ModeState:
    """Mutable mode state owned by one interactive session."""

    current: SessionMode = SessionMode.AGENT

    def allows_tool(self, name: str) -> bool:
        return self.current is SessionMode.AGENT or name in PLAN_ALLOWED_TOOLS

    def switch(self) -> SessionMode:
        self.current = (
            SessionMode.PLAN if self.current is SessionMode.AGENT
            else SessionMode.AGENT
        )
        return self.current


def mode_context(mode: SessionMode) -> str:
    if mode is SessionMode.PLAN:
        return (
            "The session is now in Plan Mode. Explore the workspace and interview "
            "the user one question at a time. Do not implement changes."
        )
    return (
        "The session is now in Agent Mode. Continue from the conversation and "
        "implement the agreed work when appropriate."
    )
