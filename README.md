# Harness

CLI coding agent. Talks to OpenRouter (`openai/gpt-5.6-luna` by default) via native function calling, and can read, list, and edit files in your workspace.

## Inspiration

This repository was inspired by [The Emperor Has No Clothes](https://www.mihaileric.com/The-Emperor-Has-No-Clothes/), a write-up about a Claude Code leak that occurred in April.

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

During a session, use `/auto-accept` to approve all subsequent edits without
prompting. Use `/auto-accept off` to restore edit confirmations. `/quit` exits
and `/help` lists session commands.

Session transcripts land in `~/harness_logs/` by default.

## Tools

The model can call:

| Tool | Purpose |
|------|---------|
| `read_file` | Read a file |
| `list_files` | List a directory |
| `search_files` | Recursively search text files, honoring `.gitignore` |
| `edit_file` | Propose and edit a file (empty `old_str` creates/overwrites) |

Edits are shown as a unified diff and require confirmation by default. If you
reject an edit, you can provide feedback and the model will receive it. Existing
files are backed up outside the repository, under `~/.harness/backups/` by
 default (or `HARNESS_BACKUP_DIR`). Each workspace gets its own folder and
 backups retain the original relative path. Git remains the durable,
 shareable history; use `git restore` or `git revert` to pull changes back to a
 point. Use
`--yes` (or `HARNESS_AUTO_APPROVE=1`) to approve edits automatically, or
`--dry-run` (or `HARNESS_DRY_RUN=1`) to preview edits without changing files.

```bash
python -m harness --yes
python -m harness --dry-run
```

Relative paths resolve under the current working directory (or `HARNESS_WORKSPACE` if set).

## Tests

Run the unit test suite with the Python standard library:

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs the suite on every push and pull request across supported
Python versions.

## Config (optional)

| Variable | Default | Meaning |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | — | **Required** |
| `OPENROUTER_MODEL` | `openai/gpt-5.6-luna` | OpenRouter model id |
| `HARNESS_WORKSPACE` | cwd | Root for relative file paths |
| `HARNESS_LOGS_DIR` | `~/harness_logs` | Session history directory |
| `HARNESS_HISTORY_FILE` | auto-named file under logs | Force a specific history path |
| `HARNESS_LOG_LEVEL` | `INFO` | Logging level |
| `HARNESS_NO_COLOR` | — | Disable ANSI colors in terminal output |
| `HARNESS_COLOR` | — | Force ANSI colors (`1`, `true`, or `always`) |

Assistant responses are rendered for terminal readability, including headings,
 emphasis, inline code, fenced code blocks, lists, blockquotes, and horizontal
rules. Set `HARNESS_NO_COLOR=1` for plain output or `HARNESS_COLOR=always` to
force colors when output is redirected.
