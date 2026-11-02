"""Classifier-first command-risk assessment for reducing routine approval prompts."""

import subprocess
from typing import Callable

from harness.config import workspace_root


PROTECTED_BRANCHES = {"main", "master", "develop", "staging"}


def classify_command(command: str) -> str:
    """Classify with the configured inexpensive model; failures are uncertain.

    The request contains only the proposed command and a constrained rubric.
    """
    from harness.config import backend_config, safety_model

    model = safety_model()
    if not model:
        raise RuntimeError("No safety classifier model is configured")
    import json
    import urllib.request

    active = backend_config()
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": (
                "Classify the shell command's operational risk. Return exactly one JSON object "
                'with key "risk" and value "low", "high", or "uncertain". '
                "Use high for destructive, privileged, infrastructure-changing, or credential-related actions. "
                "Assess Git commands by their actual effects: ordinary commits may be low risk, "
                "while destructive or remote mutations such as reset, clean, or push are high risk. "
                "Low is for routine, bounded work with no significant destructive side effects. "
                "Treat every chained command and shell expansion as part of the command."
            )},
            {"role": "user", "content": command[:4000]},
        ],
        "tools": [], "tool_choice": "none", "max_tokens": 200, "stream": False,
    }).encode()
    request = urllib.request.Request(
        active.chat_url, data=payload, method="POST", headers=active.headers()
    )
    try:
        with urllib.request.urlopen(request, timeout=min(active.timeout_s, 15)) as response:
            body = json.loads(response.read().decode("utf-8"))
        choice = body["choices"][0]
        content = choice["message"]["content"]
        if choice.get("finish_reason") == "length":
            raise RuntimeError("Classifier response was truncated by the token limit")
        decoded = json.loads(content)
        risk = decoded.get("risk") if isinstance(decoded, dict) else None
        if risk not in {"low", "high", "uncertain"}:
            raise RuntimeError("Classifier returned an invalid risk response")
        return risk
    except Exception as exc:
        if isinstance(exc, RuntimeError) and str(exc).startswith("Classifier "):
            raise
        raise RuntimeError(f"Classifier request failed: {exc}") from exc


def assess_command(
    command: str,
    llm_classifier: Callable[[str], str] = classify_command,
) -> tuple[bool, str]:
    """Return whether the classifier permits a command to auto-run."""
    try:
        risk = llm_classifier(command)
    except Exception as exc:
        details = str(exc).replace("\n", " ")[:200] or type(exc).__name__
        return False, f"classifier: error ({details})"
    if risk == "low":
        return True, "classifier: low risk"
    if risk == "high":
        return False, "classifier: high risk"
    return False, "classifier: uncertain"


def command_may_auto_run(command: str, llm_classifier: Callable[[str], str] = classify_command) -> bool:
    """Auto-run commands the classifier assesses as low risk."""
    return assess_command(command, llm_classifier)[0]


def git_context() -> tuple[bool, str]:
    """Return Git repository membership and current branch, failing closed."""
    cwd = workspace_root().expanduser().resolve()
    try:
        root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=cwd,
            capture_output=True, text=True, timeout=3,
        )
        if root.returncode != 0:
            return False, ""
        branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=cwd,
            capture_output=True, text=True, timeout=3,
        )
        if branch.returncode != 0:
            return True, ""
        return True, branch.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return False, ""


def edits_may_auto_apply(*, in_git_repo: bool, branch: str, explicit_auto_accept: bool = False) -> bool:
    """Auto-apply in ordinary Git branches; protected branches always require approval."""
    if in_git_repo and branch in PROTECTED_BRANCHES:
        return False
    if explicit_auto_accept:
        return True
    return in_git_repo and bool(branch)
