# Skills

A workspace can declare reusable, lazy-loaded instructions in `AGENTS.md`:

```markdown
## Available skills

- [Create feature](../.harness/skills/create-feature/SKILL.md)
- [Create skill](../.harness/skills/create-skill/SKILL.md)
- [Check work status](../.harness/skills/check-work-status/SKILL.md)
- [Pull request](../.harness/skills/pull-request/SKILL.md)
- [Copy to clipboard](../.harness/skills/copy-to-clipboard/SKILL.md)
- [Copy to Slack](../.harness/skills/copy-to-slack/SKILL.md)
```

Harness includes the linked skill names in the agent context. The agent can use
`load_skill` when a task requires one. Only skills explicitly linked from the
workspace instructions are available.

Each skill link must point to a `SKILL.md` file inside a skill directory. Skill
names must be lowercase kebab-case and match their directory names. Skill paths
must remain inside the workspace, and skill files are limited to 256 KiB.
Missing or invalid links are reported when the skill is loaded.

Run `make validate-skills` to validate all skills in this repository. The
validator checks the required metadata and directory naming constraints; the
official `skills-ref` validator can provide additional specification checks when
installed.
