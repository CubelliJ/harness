---
name: copy-to-clipboard
description: Copy text or file contents to the macOS clipboard. Use when the user asks to copy, place, or send text to their clipboard on macOS.
compatibility: Requires macOS and the pbcopy command.
---

# Copy to clipboard

Use the bundled script instead of invoking `pbcopy` through a shell.

## Copy text

Pipe the exact text to the script through standard input:

```bash
python .harness/skills/copy-to-clipboard/scripts/copy_to_clipboard.py <<'EOF'
Text to copy goes here.
EOF
```

For multiline content, preserve the user's formatting exactly.

## Copy a file

Copy a UTF-8 text file with:

```bash
python .harness/skills/copy-to-clipboard/scripts/copy_to_clipboard.py \
  --file path/to/file.txt
```

## Rules

- Confirm that the environment is macOS before running the script.
- Do not print or echo clipboard contents after copying.
- Do not expose sensitive clipboard contents in logs or status messages.
- Report only whether the copy operation succeeded or why it could not run.
