# Tools

Harness exposes local workspace tools to the model:

| Tool | Purpose |
|------|---------|
| `load_skill` | Load instructions explicitly linked from `AGENTS.md` |
| `read_file` | Read up to 1000 lines from a file, with pagination |
| `list_files` | List files and directories |
| `run_command` | Run a shell command, with confirmation |
| `search_files` | Search text files while honoring `.gitignore` |
| `edit_file` | Preview and edit a file |
| `git_status` | Show concise Git status (read-only) |
| `git_diff` | Inspect unstaged or staged Git diff (read-only) |
| `git_log` | Inspect recent Git commits (read-only) |
| `git_branch_list` | List local and remote branches (read-only) |

Edits are shown as unified diffs and require confirmation by default. Use
`--yes` or `/auto-accept` to approve file edits automatically. Shell commands
still require confirmation. Use `--dry-run` to preview edits without applying
them.

```bash
python -m harness --yes
python -m harness --dry-run
```

Backups are stored outside the repository under `~/.harness/backups/` by
default. Relative paths resolve from the current workspace, or from
`HARNESS_WORKSPACE` when it is set.
