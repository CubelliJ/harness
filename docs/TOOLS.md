# Tools

Harness exposes local workspace tools to the model:

| Tool | Purpose |
|------|---------|
| `load_skill` | Load instructions explicitly linked from `AGENTS.md` |
| `read_file` | Read a file |
| `list_files` | List files and directories |
| `run_command` | Run a shell command, with confirmation |
| `search_files` | Search text files while honoring `.gitignore` |
| `edit_file` | Preview and edit a file |

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
