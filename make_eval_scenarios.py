#!/usr/bin/env python3
"""Create small, real coding tasks for manually or automatically running Harness.

This creates workspaces, not fake transcripts. Run Harness against one workspace,
then pass its resulting history to eval_chat.py.
"""

import argparse
import json
from pathlib import Path

SCENARIOS = {
    "word_count": {
        "task": (
            "Modify word_count.py so it accepts a filename as its first command-line "
            "argument and prints the number of words in that file. Keep the existing "
            "default text behavior when no argument is supplied. Do not modify tests."
        ),
        "files": {
            "word_count.py": '''import sys\n\n\ndef count_words(text):\n    return len(text.split())\n\n\nif __name__ == "__main__":\n    text = "one two three"\n    print(count_words(text))\n''',
            "test_word_count.py": '''from word_count import count_words\n\n\ndef test_count_words():\n    assert count_words("one two three") == 3\n''',
            ".gitignore": "__pycache__/\n",
        },
        "checks": [
            "python word_count.py",
            "python word_count.py sample.txt",
            "python -m unittest discover -v",
        ],
        "extra_files": {"sample.txt": "one two three four\n"},
    },
    "todo_filter": {
        "task": (
            "Modify todo.py by adding a function pending(items) that returns only "
            "items whose done field is false. Preserve the input order and do not "
            "mutate the input. Add a small unittest file covering the behavior."
        ),
        "files": {
            "todo.py": '''def completed(items):\n    return [item for item in items if item["done"]]\n''',
            ".gitignore": "__pycache__/\n",
        },
        "checks": ["python -m unittest discover -v"],
        "extra_files": {},
    },
    "config_search": {
        "task": (
            "Find the configuration loader in config.py and add support for an "
            "APP_ENV environment variable, defaulting to development. Add a test "
            "for both the default and environment-variable cases. Do not change "
            "unrelated files."
        ),
        "files": {
            "config.py": '''import os\n\n\ndef load_config():\n    return {"debug": True}\n''',
            "README.md": "# Example app\n\nConfiguration is loaded by config.py.\n",
            ".gitignore": "__pycache__/\n",
        },
        "checks": ["python -m unittest discover -v"],
        "extra_files": {},
    },
}


def main():
    parser = argparse.ArgumentParser(description="Create real Harness coding-task fixtures")
    parser.add_argument(
        "--out", default=str(Path(__file__).resolve().parent / "eval_scenarios")
    )
    parser.add_argument("--scenario", choices=["all"] + list(SCENARIOS), default="all")
    args = parser.parse_args()

    selected = SCENARIOS if args.scenario == "all" else {args.scenario: SCENARIOS[args.scenario]}
    root = Path(args.out)
    manifest = {}
    for name, scenario in selected.items():
        workspace = root / name
        workspace.mkdir(parents=True, exist_ok=True)
        for filename, content in scenario["files"].items():
            path = workspace / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        for filename, content in scenario["extra_files"].items():
            (workspace / filename).write_text(content, encoding="utf-8")
        manifest[name] = {
            "workspace": str(workspace.resolve()),
            "task": scenario["task"],
            "checks": scenario["checks"],
        }
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Created %d real coding scenarios in %s" % (len(selected), root.resolve()))
    print("Run Harness with HARNESS_WORKSPACE set to one scenario directory.")


if __name__ == "__main__":
    main()
