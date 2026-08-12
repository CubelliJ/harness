"""Main entry point and agent loop."""

import logging

from harness import config, get_version
from harness.config import history_file_path
from harness.conversation import (
    ASSISTANT_PREFIX,
    YOU_PROMPT,
    assistant_message,
    save_conversation_history,
    system_message,
    tool_message,
    user_message,
)
from harness.llm import execute_llm_call, parse_tool_call
from harness.registry import (
    execute_tool,
    format_tool_result_content,
    get_full_system_prompt,
)

logger = logging.getLogger(__name__)


def _banner() -> None:
    print(
        f"\n\u001b[36m\u001b[1m"
        f"Harness v{get_version()}  |  {config.get_model()}  |  {config.workspace_root()}"
        f"\u001b[0m\n"
        "Type a request. Ctrl+C to exit.\n"
    )


def run() -> None:
    _banner()
    history_path = history_file_path()
    conversation = [system_message(get_full_system_prompt())]
    save_conversation_history(history_path, conversation)

    while True:
        try:
            user_input = input(YOU_PROMPT)
        except (KeyboardInterrupt, EOFError):
            break

        conversation.append(user_message(user_input))
        save_conversation_history(history_path, conversation)

        while True:
            content, tool_calls = execute_llm_call(conversation)

            if not tool_calls:
                conversation.append(assistant_message(content))
                save_conversation_history(history_path, conversation)
                if content:
                    print(f"{ASSISTANT_PREFIX}{content}")
                break

            if content:
                print(f"{ASSISTANT_PREFIX}{content}")

            conversation.append(assistant_message(content or None, tool_calls=tool_calls))
            save_conversation_history(history_path, conversation)

            for tc in tool_calls:
                call_id, name, args = parse_tool_call(tc)
                result = execute_tool(name, args)
                summary = (
                    result.get("error")
                    or result.get("action")
                    or result.get("path")
                    or result.get("file_path")
                    or "ok"
                )
                print(f"\u001b[90m▸ tool {name} → {summary}\u001b[0m")
                conversation.append(
                    tool_message(call_id, format_tool_result_content(name, result))
                )
            save_conversation_history(history_path, conversation)


def main() -> None:
    config.init()
    run()


if __name__ == "__main__":
    main()
