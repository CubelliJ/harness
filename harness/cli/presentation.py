"""CLI presentation, model selection, and session selection helpers."""

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from harness import config, get_version
from harness.conversation import (
    YOU_PROMPT,
    conversation_cost,
    estimated_usage_cost,
    usage_cost_breakdown,
    usage_cost_fields,
)
from harness.config import CONTEXT_COMPACTION_CAP, CONTEXT_COMPACTION_RATIO
from harness.llm import filter_models, get_available_models, get_model_pricing

logger = logging.getLogger(__name__)

def _format_tokens(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "?"


def _format_cost(value: Any) -> str:
    try:
        return f"${float(value):.6f}" if value is not None else "unknown"
    except (TypeError, ValueError):
        return "unknown"


def _cost_breakdown_text(breakdown: Dict[str, Any]) -> str:
    return (
        f"input {_format_cost(breakdown.get('input_cost'))} / "
        f"cache read {_format_cost(breakdown.get('cache_read_cost'))} / "
        f"cache write {_format_cost(breakdown.get('cache_write_cost'))} / "
        f"output {_format_cost(breakdown.get('output_cost'))} / "
        f"reasoning {_format_cost(breakdown.get('reasoning_cost'))}"
    )


def _context_bar(prompt_tokens: Optional[int], context_limit: Optional[int], width: int = 30) -> str:
    if prompt_tokens is None:
        return "[unknown]"
    if not context_limit or context_limit < 1:
        return f"[{prompt_tokens:,} tokens; limit unknown]"
    ratio = min(1.0, max(0.0, prompt_tokens / context_limit))
    filled = int(round(ratio * width))
    return "[%s%s] %d%%" % ("#" * filled, "." * (width - filled), round(ratio * 100))


def _print_context(prompt_tokens: Optional[int], context_limit: Optional[int]) -> None:
    usage = _format_tokens(prompt_tokens)
    limit = _format_tokens(context_limit) if context_limit else "unknown"
    bar = _context_bar(prompt_tokens, context_limit)
    # Keep the helper plain for scripts/tests while making the interactive
    # status line a little more luminous.
    print(f"\033[90m▸ context {usage} / {limit} tokens \033[36m{bar}\033[0m")


def _pricing_kwargs(prompt_tokens: Optional[int] = None) -> Dict[str, Optional[float]]:
    active = config.backend_config()
    discovered = get_model_pricing(prompt_tokens)
    return {
        "input_cost_per_million": (
            active.input_cost_per_million
            if active.input_cost_per_million is not None
            else discovered.get("input_cost_per_million")
        ),
        "cache_read_cost_per_million": (
            active.cache_read_cost_per_million
            if active.cache_read_cost_per_million is not None
            else discovered.get("cache_read_cost_per_million")
        ),
        "cache_write_cost_per_million": (
            active.cache_write_cost_per_million
            if active.cache_write_cost_per_million is not None
            else discovered.get("cache_write_cost_per_million")
        ),
        "output_cost_per_million": (
            active.output_cost_per_million
            if active.output_cost_per_million is not None
            else discovered.get("output_cost_per_million")
        ),
    }


def _print_cost(conversation: list[Dict[str, Any]], last: bool = False) -> None:
    summary = conversation_cost(conversation, **_pricing_kwargs())
    if not summary["calls"]:
        print("\033[90m▸ no provider usage recorded yet\033[0m")
        return
    if last:
        usage = summary["last_usage"] or {}
        fields = usage_cost_fields(usage)
        cost_text = _format_cost(usage.get("cost"))
        print(f"\033[90m▸ last call: {cost_text} · "
              f"{_format_tokens(fields['input_tokens'])} input "
              f"({_format_tokens(fields['cache_read_input_tokens'])} cache read / "
              f"{_format_tokens(fields['cache_write_input_tokens'])} cache write) · "
              f"{_format_tokens(fields['output_tokens'])} output · "
              f"{_format_tokens(fields['reasoning_tokens'])} reasoning · "
              f"{_format_tokens(fields['total_tokens'])} total\033[0m")
        provider_breakdown = usage_cost_breakdown(usage)
        estimated_breakdown = estimated_usage_cost(
            usage,
            **_pricing_kwargs(usage_cost_fields(usage)["input_tokens"]),
        )
        breakdown = {
            key: provider_breakdown[key] if provider_breakdown[key] is not None else estimated_breakdown[key]
            for key in provider_breakdown
        }
        print(f"\033[90m  cost breakdown: {_cost_breakdown_text(breakdown)}\033[0m")
        return
    cost = summary["cost"]
    cost_text = _format_cost(cost)
    print(f"\033[90m▸ conversation: {cost_text} · {summary['calls']} calls · "
          f"{_format_tokens(summary['input_tokens'])} input "
          f"({_format_tokens(summary['cache_read_input_tokens'])} cache read / "
          f"{_format_tokens(summary['cache_write_input_tokens'])} cache write) · "
          f"{_format_tokens(summary['output_tokens'])} output · "
          f"{_format_tokens(summary['reasoning_tokens'])} reasoning · "
          f"{_format_tokens(summary['total_tokens'])} total\033[0m")
    print(f"\033[90m  cost breakdown: {_cost_breakdown_text(summary['cost_breakdown'])}\033[0m")


def _format_model_context(model: Dict[str, Any]) -> str:
    context = model.get("context_length")
    return f"{int(context):,}" if context is not None else "?"


def _git_branch() -> str:
    """Return the current branch for the workspace, or a friendly fallback."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=config.workspace_root(),
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "no-git"
    branch = result.stdout.strip()
    if branch:
        return branch
    return "detached" if result.returncode == 0 else "no-git"


def _prompt() -> str:
    """Build the prompt with a fresh branch badge for every interaction."""
    return f"{YOU_PROMPT}\033[35m⎇ {_git_branch()}\033[0m  "


def _select_saved_session(sessions: list[Dict[str, Any]]) -> Optional[Path]:
    """Prompt for one of the recent saved sessions; choose newest on non-TTY input."""
    if not sessions:
        return None
    print("\033[36mRecent conversations:\033[0m")
    for index, session in enumerate(sessions[:5], 1):
        title = session.get("title") or "Untitled conversation"
        updated = session.get("updated", "")
        print(f"  {index}. {title} \033[90m{updated}\033[0m")
    if not sys.stdin.isatty():
        return Path(sessions[0]["path"])
    count = min(5, len(sessions))
    choice_label = "1" if count == 1 else f"1-{count}"
    try:
        answer = input(f"Resume [{choice_label}, Enter to cancel]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if not answer:
        return None
    try:
        index = int(answer)
    except ValueError:
        print("\033[90m▸ enter a conversation number\033[0m")
        return None
    if not 1 <= index <= min(5, len(sessions)):
        print("\033[90m▸ no conversation with that number\033[0m")
        return None
    return Path(sessions[index - 1]["path"])


def _select_model(
    argument: str = "",
    *,
    models_loader=get_available_models,
    model_filter=filter_models,
    offer_workspace_default=None,
) -> Optional[str]:
    """List models, filter by search text, or select one by number/id.

    ``/model`` lists everything, ``/model open`` lists models matching "open",
    ``/model open 2`` picks the second match, and a bare number or exact
    provider/model-id still selects from the full catalogue.
    """
    try:
        models = models_loader()
    except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"\033[91m\u25b8 model catalogue unavailable: {exc}\033[0m")
        return None
    if not models:
        print(f"\033[90m\u25b8 {config.backend_config().display_name} returned no models\033[0m")
        return None
    query = argument.strip()

    def _switch(model: Dict[str, Any]) -> str:
        config.set_model(model["id"])
        print(f"\033[90m\u25b8 model switched to {model['id']}\033[0m")
        (offer_workspace_default or _offer_workspace_default)(model["id"])
        return model["id"]

    if query.isdigit():
        if 1 <= int(query) <= len(models):
            return _switch(models[int(query) - 1])
        print(f"\033[90m\u25b8 enter a model number 1-{len(models)} or an exact model id\033[0m")
        return None
    if query:
        exact = next((m for m in models if m["id"].lower() == query.lower()), None)
        if exact is not None:
            return _switch(exact)

    filter_text = query
    pick = None
    parts = query.split()
    if len(parts) > 1 and parts[-1].isdigit():
        filter_text = " ".join(parts[:-1])
        pick = int(parts[-1])
    if filter_text:
        models = model_filter(models, filter_text)
        if not models:
            print(f"\033[90m\u25b8 no models matching {filter_text!r}\033[0m")
            return None
    if pick is not None:
        if 1 <= pick <= len(models):
            return _switch(models[pick - 1])
        print(f"\033[90m\u25b8 choose a model number 1-{len(models)} from /model {filter_text}\033[0m")
        return None

    print(f"\033[36mAvailable models from {config.backend_config().display_name}:\033[0m")
    for index, model in enumerate(models, 1):
        name = model.get("name") or model["id"]
        print(f"  {index:>3}. {name}  \033[90m{model['id']} \u00b7 {_format_model_context(model)} tokens\033[0m")
    saved_default = config.workspace_model()
    if saved_default:
        print(f"\033[90mWorkspace default: {saved_default}\033[0m")
    if query:
        print(f"\033[90m{len(models)} matching models for {filter_text!r}; pick with /model {filter_text} <number>\033[0m")
    else:
        print("\033[90mUse /model <number>, /model <provider/model-id>, or /model <search text>\033[0m")
    return None


def _offer_workspace_default(model_id: str) -> None:
    """Offer to persist a freshly selected model as this workspace's default."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return
    if config.workspace_model() == model_id:
        return
    try:
        answer = input(
            f"Save {model_id} as the default model for this workspace? [y/N]: "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if answer not in {"y", "yes"}:
        print("\033[90m▸ keeping the session-only model\033[0m")
        return
    try:
        path = config.save_workspace_model(model_id)
    except OSError as exc:
        print(f"\033[91m▸ could not save workspace default: {exc}\033[0m")
        return
    print(f"\033[90m▸ saved as workspace default in {path}\033[0m")


def _banner() -> None:
    """Show a compact, decorative welcome dashboard before the REPL starts."""
    cyan = "\u001b[36m"
    dim = "\u001b[90m"
    white = "\u001b[97m"
    reset = "\u001b[0m"
    title = f"◈  H A R N E S S   {get_version()}"
    model = config.get_model()
    workspace = str(config.workspace_root())
    print(
        f"\n{cyan}\u001b[1m   ╭────────────────────────────────────────────╮{reset}\n"
        f"{cyan}\u001b[1m   │{title.center(44)}│{reset}\n"
        f"{cyan}\u001b[1m   ╰────────────────────────────────────────────╯{reset}\n"
        f"{dim}   ◌ model      {white}{model}{reset}\n"
        f"{dim}   ◌ workspace  {white}{workspace}{reset}\n"
        f"{dim}   ◌ branch     {white}⎇ {_git_branch()}{reset}\n"
        f"{dim}   ────────────────────────────────────────────{reset}\n"
        f"{cyan}   ◆ ready{reset}  {dim}Type a request · Escape interrupts · /help for shortcuts{reset}\n"
    )

