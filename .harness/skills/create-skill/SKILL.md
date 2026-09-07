---
name: create-skill
description: Create or update repository skills as Agent Skills. Use when adding, defining, or improving a reusable skill, especially when its SKILL.md metadata, directory layout, AGENTS.md registration, or validation needs attention.
---

# Create a skill

Use this workflow when asked to create, add, or define a repository skill.

## How skills work in this repository

Skills follow the Agent Skills format: each skill is a directory containing a
`SKILL.md` file with YAML frontmatter and Markdown instructions. Skills are
lazy-loaded: only skills linked from the workspace `AGENTS.md` are included in
the available skill catalog, and their full contents are loaded only when the
assistant calls `load_skill`.

Use lowercase kebab-case for the skill directory and frontmatter `name`; they
must match. Include a non-empty `description` in the frontmatter that explains
what the skill does and when to use it.

Skills must be listed in a single `## Skills` section in `AGENTS.md`. Link to
the directory's `SKILL.md` and use the canonical skill name as the link text,
without adding the word "skill":

```markdown
## Skills

- Run tests: [testing](.harness/skills/testing.md)
```

The link text is the canonical skill name used by `load_skill`. Keep it short,
descriptive, and consistent with the skill filename. The path must remain
inside the workspace, and the file must be no larger than 256 KiB.

## Creation workflow

1. Inspect `AGENTS.md`, the existing `.harness/skills` directory, and relevant
   implementation or README documentation before editing.
2. Choose a short, descriptive kebab-case filename under
   `.harness/skills/<name>.md`.
3. Write focused, imperative instructions describing when the skill applies and
   the steps the assistant should follow. Include commands, constraints, and
   validation guidance when relevant.
4. Add a Markdown link to the new skill in `AGENTS.md`. Do not assume an
   unlinked file can be loaded.
5. Avoid duplicating repository-wide instructions; link to existing guidance or
   summarize only what the skill needs.
6. Review the new file and the focused diff. Preserve unrelated working-tree
   changes.
7. If the skill changes Python behavior, run the focused unit tests. For
   documentation-only skill changes, validate the Markdown link and file
   existence instead.

Before reporting completion, state the skill name and path, the `AGENTS.md`
link, validation performed, and whether the change was committed. Do not claim
that a skill is available to the loader until it is linked from `AGENTS.md`.
