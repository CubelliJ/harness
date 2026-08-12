# Harness

CLI coding agent. Talks to OpenRouter (`openai/gpt-5.6-luna` by default) via native function calling, and can read, list, and edit files in your workspace.

## Requirements

- Python 3.9+
- An [OpenRouter](https://openrouter.ai/) API key

No third-party packages — stdlib only.

## Setup

```bash
cd /path/to/harness
```

Create a `.env` in the project root (or export the variable):

```bash
OPENROUTER_API_KEY=sk-or-...
```

## Run

From the directory that contains the `harness/` package:

```bash
python -m harness
```

You’ll get a REPL. Type a request, press Enter. Use **Shift+Enter** to insert a
newline without submitting (in terminals that report modified keys), and press
Enter to submit. Ctrl+C to exit. Bracketed paste also preserves newlines.

Session transcripts land in `~/harness_logs/` by default.

## Tools

The model can call:

| Tool | Purpose |
|------|---------|
| `read_file` | Read a file |
| `list_files` | List a directory |
| `edit_file` | Propose and edit a file (empty `old_str` creates/overwrites) |

Edits are shown as a unified diff and require confirmation by default. Existing
files are backed up to `<filename>.harness.bak` before replacement. Use
`--yes` (or `HARNESS_AUTO_APPROVE=1`) to approve edits automatically, or
`--dry-run` (or `HARNESS_DRY_RUN=1`) to preview edits without changing files.

```bash
python -m harness --yes
python -m harness --dry-run
```

Relative paths resolve under the current working directory (or `HARNESS_WORKSPACE` if set).

## Config (optional)

| Variable | Default | Meaning |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | — | **Required** |
| `OPENROUTER_MODEL` | `openai/gpt-5.6-luna` | OpenRouter model id |
| `HARNESS_WORKSPACE` | cwd | Root for relative file paths |
| `HARNESS_LOGS_DIR` | `~/harness_logs` | Session history directory |
| `HARNESS_HISTORY_FILE` | auto-named file under logs | Force a specific history path |
| `HARNESS_LOG_LEVEL` | `INFO` | Logging level |
