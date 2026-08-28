"""Provider and tool execution loop for the interactive CLI."""

import json
import sys
from typing import Any, Callable, Dict, Optional

from harness import config
from harness.conversation import (
    ASSISTANT_PREFIX,
    assistant_message,
    tool_message,
    user_message,
)
from harness.llm import execute_llm_call, parse_tool_call
from harness.registry import execute_tool, format_tool_result_content
from harness.terminal import MarkdownStreamRenderer, render_markdown


Conversation = list[Dict[str, Any]]
InterruptibleCall = Callable[..., Any]
Persist = Callable[[], None]
Compact = Callable[[], bool]
ConfirmCommand = Callable[[str], tuple[bool, str]]
ConfirmEdit = Callable[[Dict[str, Any]], tuple[bool, str]]
UpdateTokens = Callable[[Optional[int]], None]
GenerateTitle = Callable[[], None]


def _append_interrupted_tool_results(conversation: Conversation) -> None:
    """Close the latest unfinished tool-call turn after an interruption."""
    assistant_index = None
    for index in range(len(conversation) - 1, -1, -1):
        message = conversation[index]
        if message.get("role") == "assistant" and message.get("tool_calls"):
            assistant_index = index
            break
    if assistant_index is None:
        return
    trailing = conversation[assistant_index + 1:]
    if any(message.get("role") != "tool" for message in trailing):
        return
    calls = conversation[assistant_index].get("tool_calls") or []
    completed = {
        message.get("tool_call_id")
        for message in trailing
        if message.get("role") == "tool"
    }
    for index, call in enumerate(calls):
        call_id = call.get("id") if isinstance(call, dict) else None
        if not isinstance(call_id, str) or not call_id:
            call_id = f"interrupted-tool-{index}"
        if call_id not in completed:
            conversation.append(tool_message(
                call_id,
                json.dumps({"error": "interrupted by user; tool was not run"}),
            ))


def _tool_status(name: str, summary: str) -> str:
    """Format a tool result as a small decorative status badge."""
    summary = str(summary)
    failed = summary.startswith(("error", "rejected")) or "_rejected" in summary
    icon = "!" if failed else "✓"
    color = "\033[91m" if failed else "\033[92m"
    return f"\033[90m   ├─ {color}{icon}\033[0m \033[96m{name}\033[0m \033[90m· {summary}\033[0m"


def run_turn(
    conversation: Conversation,
    *,
    session_auto_approve: bool,
    compact: Compact,
    persist: Persist,
    maybe_generate_title: GenerateTitle,
    confirm_command: ConfirmCommand,
    confirm_edit: ConfirmEdit,
    interruptible_call: InterruptibleCall,
    update_tokens: UpdateTokens,
) -> None:
    """Run provider responses and tool calls until the assistant answers."""
    while True:
        compact()
        streamed_text = False
        markdown_renderer = MarkdownStreamRenderer()

        def on_text(fragment: str) -> None:
            nonlocal streamed_text
            rendered = markdown_renderer.feed(fragment)
            if not rendered:
                return
            if not streamed_text:
                sys.stdout.write(ASSISTANT_PREFIX)
                streamed_text = True
            sys.stdout.write(rendered)
            sys.stdout.flush()

        content, tool_calls, usage = interruptible_call(
            execute_llm_call, conversation, on_text=on_text
        )
        tail = markdown_renderer.finish()
        if tail:
            if not streamed_text:
                sys.stdout.write(ASSISTANT_PREFIX)
                streamed_text = True
            sys.stdout.write(tail)
        if streamed_text:
            sys.stdout.write("\n")
            sys.stdout.flush()

        raw_prompt_tokens = usage.get("prompt_tokens")
        if isinstance(raw_prompt_tokens, int) and not isinstance(raw_prompt_tokens, bool):
            update_tokens(raw_prompt_tokens)
        if not tool_calls:
            conversation.append(assistant_message(content, usage=usage))
            persist()
            maybe_generate_title()
            if content and not streamed_text:
                print(f"{ASSISTANT_PREFIX}{render_markdown(content)}")
            return

        if content and not streamed_text:
            print(f"{ASSISTANT_PREFIX}{render_markdown(content)}")
        conversation.append(assistant_message(content or None, tool_calls=tool_calls, usage=usage))
        persist()

        preflight_error: Optional[str] = None
        for tool_call in tool_calls:
            try:
                parse_tool_call(tool_call)
            except ValueError as exc:
                preflight_error = str(exc)
                break

        for tool_call in tool_calls:
            # A malformed model response must become a tool error, not a
            # filesystem operation or a crashed session. Preserve the call id
            # when possible so the provider can continue the exchange.
            try:
                call_id, name, args = parse_tool_call(tool_call)
            except ValueError as exc:
                call_id = tool_call.get("id") if isinstance(tool_call, dict) else ""
                call_id = call_id or "invalid-tool-call"
                name = ((tool_call.get("function") or {}).get("name", "invalid")
                        if isinstance(tool_call, dict)
                        and isinstance(tool_call.get("function"), dict)
                        else "invalid")
                args = {}
                result = {"error": str(exc)}
            else:
                if preflight_error:
                    result = {"error": f"tool turn rejected: {preflight_error}"}
                elif name == "run_command":
                    approved, feedback = confirm_command(args.get("command", ""))
                    if approved:
                        result = interruptible_call(execute_tool, name, args)
                    else:
                        result = {"action": "command_rejected"}
                        if feedback:
                            result["feedback"] = feedback
                elif name == "edit_file":
                    preview_args = dict(args, apply=False)
                    result = interruptible_call(execute_tool, name, preview_args)
                    if not result.get("error") and result.get("action") != "old_str not found":
                        if config.dry_run():
                            result["action"] = "dry_run"
                        elif session_auto_approve:
                            result = interruptible_call(
                                execute_tool, name, dict(args, apply=True)
                            )
                        else:
                            approved, feedback = confirm_edit(result)
                            if approved:
                                result = interruptible_call(
                                    execute_tool, name, dict(args, apply=True)
                                )
                            else:
                                result["action"] = "edit_rejected"
                                result.pop("diff", None)
                                if feedback:
                                    result["feedback"] = feedback
                else:
                    result = interruptible_call(execute_tool, name, args)

            summary = (result.get("error") or result.get("action") or
                       result.get("path") or result.get("file_path") or "ok")
            print(_tool_status(name, summary))
            conversation.append(tool_message(call_id, format_tool_result_content(name, result)))
            if name == "read_image" and result.get("image_url") and not result.get("error"):
                conversation.append(user_message(
                    f"Visual context loaded from {result.get('file_path', 'the image file')}.",
                    [{"type": "image_url", "image_url": {"url": result["image_url"]}}],
                ))
                conversation[-1]["image_context"] = True
        persist()
