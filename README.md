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

During a session, use `/auto-accept` to approve all subsequent file edits without
prompting. Shell commands always require explicit human approval; `/auto-accept`
does not bypass command confirmations. Use `/auto-accept off` to restore edit
confirmations. `/quit` exits and `/help` lists session commands.

Session transcripts land in `~/harness_logs/` by default.

## Tools

The model can call:

| Tool | Purpose |
|------|---------|
| `read_file` | Read a file |
| `list_files` | List a directory |
| `search_files` | Recursively search text files, honoring `.gitignore` |
| `run_command` | Run a workspace shell command, such as tests or a formatter |
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

## Evaluation workflow

Both the Harness CLI and `eval_chat.py` load `.env` from this repository root, even
when `HARNESS_WORKSPACE` points at an evaluation scenario. Shell environment
variables still take precedence over `.env`.

Create the scenario workspaces and manifest:

```bash
python make_eval_scenarios.py
```

Run an agent on one scenario without any interactive input. `--scenario` loads
its task from the manifest and the command exits after the agent finishes:

```bash
HARNESS_WORKSPACE="$PWD/eval_scenarios/word_count" \\
HARNESS_HISTORY_FILE="$PWD/eval_scenarios/word_count/history.txt" \\
python -m harness --yes --scenario word_count
```

The equivalent explicit form is:

```bash
python -m harness --yes --request "Modify word_count.py so it accepts a filename as its first command-line argument and prints the number of words in that file. Keep the existing default text behavior when no argument is supplied. Do not modify tests."
```

Evaluate all available scenario transcripts at once:

```bash
python eval_chat.py
```

The evaluator finds each scenario's `history.txt` and task from the manifest.
To evaluate only one scenario, use:

```bash
python eval_chat.py --scenario word_count
```

Use `--yes` for unattended runs (or omit it to review edits). The evaluator
uses `EVAL_API_KEY`, or falls back to
`OPENROUTER_API_KEY` from `.env`; `EVAL_MODEL` and `EVAL_URL` are also supported.
The complete unattended flow is:

```bash
python make_eval_scenarios.py
python -m harness --yes --scenario word_count
python eval_chat.py eval_scenarios/word_count/history.txt --scenario word_count
```

Keep the two `HARNESS_*` assignments on the same command (or export them); a
standalone assignment affects only that one shell command and does not persist.

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
