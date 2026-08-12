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
    user_message,
)
from harness.llm import execute_llm_call
from harness.registry import (
    execute_tool,
    extract_tool_invocations,
    format_tool_user_message,
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
            text, printed = execute_llm_call(conversation)
            tools = extract_tool_invocations(text)
            conversation.append(assistant_message(text))
            save_conversation_history(history_path, conversation)

            if not tools:
                if not printed:
                    print(f"{ASSISTANT_PREFIX}{text}")
                break

            for name, args in tools:
                result = execute_tool(name, args)
                conversation.append(user_message(format_tool_user_message(name, result)))
                save_conversation_history(history_path, conversation)


def main() -> None:
    config.init()
    run()


if __name__ == "__main__":
    main()
