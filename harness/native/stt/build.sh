#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$ROOT/harness-stt.app}"

if [[ "$OUT" != *.app ]]; then
  OUT="${OUT}.app"
fi

if ! command -v swiftc >/dev/null 2>&1; then
  echo "swiftc not found. Install Xcode Command Line Tools: xcode-select --install" >&2
  exit 1
fi

CONTENTS="$OUT/Contents"
MACOS="$CONTENTS/MacOS"
rm -rf "$OUT"
mkdir -p "$MACOS"
cp "$ROOT/Info.plist" "$CONTENTS/Info.plist"

swiftc -O -o "$MACOS/harness-stt" "$ROOT/main.swift" \
  -framework Speech \
  -framework AVFoundation \
  -framework AppKit \
  -framework Foundation \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$ROOT/Info.plist"

chmod +x "$MACOS/harness-stt"
codesign --force --sign - --identifier dev.harness.stt "$OUT" >/dev/null
