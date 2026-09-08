#!/usr/bin/env python3
"""Copy text from stdin or a file to the macOS clipboard."""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy text from stdin or a UTF-8 file to the macOS clipboard."
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Read clipboard content from this UTF-8 file instead of stdin.",
    )
    return parser.parse_args()


def main() -> int:
    if platform.system() != "Darwin":
        print(
            "copy-to-clipboard requires macOS; pbcopy is unavailable here.",
            file=sys.stderr,
        )
        return 2

    args = parse_args()
    try:
        text = (
            args.file.read_text(encoding="utf-8")
            if args.file is not None
            else sys.stdin.read()
        )
    except OSError as exc:
        print(f"Could not read input: {exc}", file=sys.stderr)
        return 1

    try:
        subprocess.run(["pbcopy"], input=text, text=True, check=True)
    except FileNotFoundError:
        print("pbcopy was not found on this macOS system.", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"pbcopy failed with exit code {exc.returncode}.", file=sys.stderr)
        return 1

    print("Copied text to the macOS clipboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
