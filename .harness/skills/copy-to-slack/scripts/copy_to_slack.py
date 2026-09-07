#!/usr/bin/env python3
"""Copy HTML and plain text representations to the macOS clipboard."""

from __future__ import annotations

import argparse
import html
import json
import os
import platform
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


JXA = r'''
ObjC.import("AppKit");
ObjC.import("Foundation");
var values = JSON.parse($.NSProcessInfo.processInfo.environment.objectForKey("HARNESS_CLIPBOARD_PAYLOAD").js);
var pasteboard = $.NSPasteboard.generalPasteboard;
pasteboard.clearContents;
pasteboard.setStringForType($(values.html), "public.html");
pasteboard.setStringForType($(values.plain), "public.utf8-plain-text");
'''

ALLOWED_TAGS = {
    "br", "code", "em", "li", "ol", "p", "pre", "strong", "ul", "a"
}
ACTIVE_TAGS = {"embed", "form", "iframe", "object", "script", "style"}
ALLOWED_SCHEMES = {"", "http", "https", "mailto"}


class SafeHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.output = []
        self.active_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ACTIVE_TAGS:
            self.active_depth += 1
            return
        if self.active_depth or tag not in ALLOWED_TAGS:
            return
        safe_attrs = []
        for name, value in attrs:
            name = name.lower()
            if name.startswith("on") or name not in {"href", "title"}:
                continue
            if name == "href" and not is_safe_url(value or ""):
                continue
            safe_attrs.append((name, value))
        rendered_attrs = "".join(
            f' {name}="{html.escape(value or "", quote=True)}"'
            for name, value in safe_attrs
        )
        self.output.append(f"<{tag}{rendered_attrs}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ACTIVE_TAGS and self.active_depth:
            self.active_depth -= 1
        elif not self.active_depth and tag in ALLOWED_TAGS and tag != "br":
            self.output.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.active_depth:
            self.output.append(html.escape(data, quote=False))

    def handle_entityref(self, name):
        if not self.active_depth:
            self.output.append(f"&{name};")

    def handle_charref(self, name):
        if not self.active_depth:
            self.output.append(f"&#{name};")

    def sanitized(self):
        return "".join(self.output)


def is_safe_url(value):
    return urlsplit(value.strip()).scheme.lower() in ALLOWED_SCHEMES


def sanitize_html(value):
    parser = SafeHTMLParser()
    parser.feed(value)
    parser.close()
    return parser.sanitized()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy HTML and plain text to the macOS clipboard."
    )
    parser.add_argument(
        "--html-file",
        required=True,
        type=Path,
        help="Read the rich HTML representation from this UTF-8 file.",
    )
    return parser.parse_args()


def main() -> int:
    if platform.system() != "Darwin":
        print(
            "copy-to-slack requires macOS; osascript is unavailable here.",
            file=sys.stderr,
        )
        return 2

    args = parse_args()
    try:
        html = sanitize_html(args.html_file.read_text(encoding="utf-8"))
        plain = sys.stdin.read()
    except OSError as exc:
        print(f"Could not read input: {exc}", file=sys.stderr)
        return 1

    payload = json.dumps({"html": html, "plain": plain}, ensure_ascii=False)
    environment = os.environ.copy()
    environment["HARNESS_CLIPBOARD_PAYLOAD"] = payload
    try:
        subprocess.run(
            ["osascript", "-l", "JavaScript"],
            input=JXA,
            text=True,
            check=True,
            env=environment,
            capture_output=True,
        )
    except FileNotFoundError:
        print("osascript was not found on this macOS system.", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"osascript failed with exit code {exc.returncode}.", file=sys.stderr)
        return 1

    print("Copied Slack HTML and plain text to the macOS clipboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
