"""Conservative command-risk assessment for reducing routine approval prompts."""

import re
import shlex
import subprocess
from typing import Callable, Optional

from harness.config import workspace_root


SAFE_COMMANDS = {
    "pytest", "unittest", "tox", "nox", "ruff", "black", "flake8", "mypy",
    "pyright", "isort", "coverage", "python", "python3", "go", "cargo", "make", "npm", "pnpm",
    "yarn", "bun", "vitest", "jest", "prettier", "eslint", "tsc",
}
PROTECTED_BRANCHES = {"main", "master", "develop", "staging"}


def _split_commands(command: str) -> Optional[list[list[str]]]:
    """Tokenize shell syntax; only simple sequential/conditional chains are parsed."""
    if any(marker in command for marker in ("$", "`")):
        return None
    try:
        lexer = shlex.shlex(command.replace("\n", ";"), posix=True, punctuation_chars=";&|<>()")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return None
    commands: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token and all(char in ";&|<>()" for char in token):
            if token not in {"&&", "||", ";"} or not current:
                return None
            commands.append(current)
            current = []
        else:
            current.append(token)
    if current:
        commands.append(current)
    # Redirections, grouping, substitutions, or command wrappers defeat the
    # limited tokenizer; keep them on the interactive approval path.
    if any(token.startswith(("<", ">", "(", ")", "|")) for group in commands for token in group):
        return None
    if any(group and group[0] in {"env", "xargs", "sh", "bash", "zsh", "command", "eval"} for group in commands):
        return None
    return commands or None


def _head(tokens: list[str]) -> tuple[str, list[str]]:
    """Return executable basename, skipping simple environment assignments."""
    index = 0
    while index < len(tokens) and "=" in tokens[index] and not tokens[index].startswith("="):
        index += 1
    if index >= len(tokens):
        return "", []
    executable = tokens[index].rsplit("/", 1)[-1]
    return executable, tokens[index + 1:]


def _is_hard_risk(tokens: list[str]) -> bool:
    executable, args = _head(tokens)
    lowered = [token.lower() for token in tokens]
    if executable in {"rm", "rmdir", "dd", "mkfs", "shred", "sudo", "doas"}:
        return True
    if executable in {"python", "python3", "node", "ruby", "perl"} and any(
        arg in {"-c", "-e", "--eval"} for arg in args
    ):
        return True
    # Keep infrastructure and shell-level Git operations on the approval
    # path; command_may_auto_run has a narrow exception for simple feature-branch commits.
    if executable in {"terraform", "pulumi", "aws", "az", "gcloud", "kubectl", "helm", "git"}:
        return True
    # Catch destructive commands embedded after wrappers or command separators.
    if any(token in {"rm", "dd", "mkfs", "terraform", "pulumi"} for token in lowered):
        return True
    if executable in {"curl", "wget"} and any(token in {"sh", "bash", "zsh"} for token in lowered):
        return True
    return False


def _is_known_validation(tokens: list[str]) -> bool:
    executable, args = _head(tokens)
    if executable not in SAFE_COMMANDS:
        return False
    if executable in {"python", "python3"}:
        return len(args) >= 2 and args[0] == "-m" and args[1] in {
            "unittest", "pytest", "doctest", "compileall"
        }
    if executable == "go":
        return bool(args) and args[0] in {"test", "vet"}
    if executable == "cargo":
        return bool(args) and args[0] in {"test", "check", "clippy", "fmt"}
    if executable == "make":
        return not args or all(arg in {"test", "check", "lint", "format", "validate"} for arg in args if not arg.startswith("-"))
    if executable in {"npm", "pnpm", "yarn", "bun"}:
        scripts = {"test", "lint", "check", "typecheck", "format", "type-check"}
        if not args:
            return False
        if args[0] in scripts:
            return True
        return len(args) >= 2 and args[0] == "run" and args[1] in scripts
    if executable in {"vitest", "jest"}:
        return not args or "run" in args
    return executable in {"pytest", "unittest", "tox", "nox", "ruff", "black", "flake8", "mypy", "pyright", "isort", "coverage", "prettier", "eslint", "tsc"}


def deterministic_command_risk(command: str) -> str:
    """Return ``safe``, ``high``, or ``unknown`` from conservative local rules."""
    if re.search(r"\b(?:curl|wget)\b[^\n]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh)\b", command):
        return "high"
    commands = _split_commands(command)
    if not commands:
        return "unknown"
    if any(_is_hard_risk(tokens) for tokens in commands):
        return "high"
    if all(_is_known_validation(tokens) for tokens in commands):
        return "safe"
    return "unknown"


def classify_command(command: str) -> str:
    """Classify with the configured inexpensive model; failures are uncertain.

    The request contains only the proposed command and a constrained rubric.
    """
    from harness.config import backend_config, safety_model

    model = safety_model()
    if not model:
        return "uncertain"
    import json
    import urllib.request

    active = backend_config()
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": (
                "Classify the shell command's operational risk. Return exactly one JSON object "
                'with key "risk" and value "low", "high", or "uncertain". '
                "Use high for destructive, privileged, infrastructure-changing, credential, "
                "or Git-mutating actions; low only for routine read-only or validation work. "
                "Treat every chained command and shell expansion as part of the command."
            )},
            {"role": "user", "content": command[:4000]},
        ],
        "tools": [], "tool_choice": "none", "max_tokens": 30, "stream": False,
    }).encode()
    request = urllib.request.Request(
        active.chat_url, data=payload, method="POST", headers=active.headers()
    )
    try:
        with urllib.request.urlopen(request, timeout=min(active.timeout_s, 15)) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        decoded = json.loads(content)
        risk = decoded.get("risk") if isinstance(decoded, dict) else None
        return risk if risk in {"low", "high", "uncertain"} else "uncertain"
    except Exception:
        return "uncertain"


def _is_feature_branch_commit(command: str) -> bool:
    """Allow a plain commit on feature branches, but no other Git mutations."""
    commands = _split_commands(command)
    if not commands or len(commands) != 1:
        return False
    executable, args = _head(commands[0])
    if executable != "git" or not args or args[0] != "commit":
        return False

    # Permit only a simple message and/or commit-all flag. This deliberately
    # excludes amend, hooks bypass, arbitrary options, and path-limited commits.
    index = 1
    while index < len(args):
        option = args[index]
        if option in {"-a", "--all"}:
            index += 1
        elif option in {"-m", "--message"} and index + 1 < len(args) and args[index + 1]:
            index += 2
        else:
            return False

    in_git_repo, branch = git_context()
    return in_git_repo and branch.startswith("feature/") and bool(branch[len("feature/"):])


def command_may_auto_run(command: str, llm_classifier: Callable[[str], str] = classify_command) -> bool:
    """Auto-run safe validations, feature-branch commits, or low-risk classifications."""
    if _is_feature_branch_commit(command):
        return True
    risk = deterministic_command_risk(command)
    if _split_commands(command) is None:
        return False
    if risk == "safe":
        return True
    if risk == "high":
        return False
    try:
        return llm_classifier(command) == "low"
    except Exception:
        return False


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
