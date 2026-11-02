# Skills

A workspace can declare reusable, lazy-loaded instructions in `AGENTS.md`:

```markdown
## Available skills

- [Create feature](../.harness/skills/create-feature/SKILL.md)
- [Check work status](../.harness/skills/check-work-status/SKILL.md)
- [Pull request](../.harness/skills/pull-request/SKILL.md)
```

Harness includes available skill names in the agent context. The agent can use
`load_skill` when a task requires one. Workspace skills in the supported skill
directories are discovered automatically; skills stored elsewhere can be linked
from the workspace instructions. User and installation skills are also
available automatically.

Skills can come from these locations, in descending precedence:

1. Workspace: `<workspace>/.harness/skills/`, then `.agents/skills/`,
   `.claude/skills/`, `.cursor/skills/`, and `.codex/skills/`
2. User: `~/.harness/skills/`
3. Installation: the installed Harness package's `skills/` directory

Skills directly under these workspace directories are discovered automatically;
`AGENTS.md` links remain supported for workspace skills stored elsewhere. User
and installation skills are also discovered automatically. If the same skill
name exists in multiple locations, the higher-precedence location wins.

Each skill must contain a `SKILL.md` file inside a skill directory. Skill names
must be lowercase kebab-case and match their directory names. Skill paths must
remain inside their source root, and skill files are limited to 256 KiB.
Missing or invalid workspace links are reported when the skill is loaded.

Run `make validate-skills` to validate all skills in this repository. The
validator checks the required metadata and directory naming constraints; the
official `skills-ref` validator can provide additional specification checks when
installed.
