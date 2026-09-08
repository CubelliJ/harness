---
name: create-skill
description: Create or update repository skills as Agent Skills. Use when adding, defining, or improving a reusable skill, especially when its SKILL.md metadata, directory layout, AGENTS.md registration, or validation needs attention.
---

# Create a skill

Use this workflow when asked to create, add, or define a repository skill.

## How skills work in this repository

Skills follow the Agent Skills format: each skill is a directory containing a
`SKILL.md` file with YAML frontmatter and Markdown instructions. Skills are
listed in the available skill catalog without loading their full contents; the
assistant loads the contents only when it calls `load_skill`.

Skills under the canonical workspace directory, `.harness/skills/<name>/`, are
discovered automatically. User skills under `~/.harness/skills/<name>/` and
installed skills are also discovered automatically. Workspace skills stored
elsewhere must be linked from `AGENTS.md` to be discoverable. In all cases, use
lowercase kebab-case for the skill directory and frontmatter `name`; they must
match. Include a non-empty `description` in the frontmatter that explains what
the skill does and when to use it.

For skills stored outside `.harness/skills/`, add a Markdown link in the
workspace `AGENTS.md` and use the canonical skill name as the link text,
without adding the word "skill":

```markdown
## Skills

- Run tests: [testing](skills/testing/SKILL.md)
```

The link text is the canonical skill name used by `load_skill`. Keep it short,
descriptive, and consistent with the skill directory name. Linked paths must
remain inside the workspace, and every skill file must be no larger than
256 KiB.

## Creation workflow

1. Inspect the existing `.harness/skills` directory, `AGENTS.md` when relevant,
   and relevant implementation or README documentation before editing.
2. Choose a short, descriptive kebab-case directory under
   `.harness/skills/<name>/` and place the skill instructions in
   `.harness/skills/<name>/SKILL.md`.
3. Write focused, imperative instructions describing when the skill applies and
   the steps the assistant should follow. Include commands, constraints, and
   validation guidance when relevant.
4. If the skill is stored outside `.harness/skills/`, add a Markdown link to its
   `SKILL.md` in `AGENTS.md`. Canonical `.harness/skills/<name>/` skills do not
   need an `AGENTS.md` link.
5. Avoid duplicating repository-wide instructions; link to existing guidance or
   summarize only what the skill needs.
6. Review the new file and the focused diff. Preserve unrelated working-tree
   changes.
7. If the skill changes Python behavior, run the focused unit tests. For
   documentation-only skill changes, validate the file and any required
   `AGENTS.md` link instead.

Before reporting completion, state the skill name and path, whether an
`AGENTS.md` link was required, validation performed, and whether the change was
committed.
