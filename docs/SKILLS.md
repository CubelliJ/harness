# Skills

A workspace can declare reusable, lazy-loaded instructions in `AGENTS.md`:

```markdown
## Available skills

- [Testing](.harness/skills/testing.md)
- [Release process](.harness/skills/release.md)
```

Harness includes the linked skill names in the agent context. The agent can use
`load_skill` when a task requires one. Only skills explicitly linked from the
workspace instructions are available.

Skill paths must remain inside the workspace, and skill files are limited to
256 KiB. Missing or invalid links are reported when the skill is loaded.
