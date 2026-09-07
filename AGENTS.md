# Repository instructions

## Scope

This is the harness repository. Prefer investigating harness/*.py and README.md
when the task concerns harness itself; include tests/ when behavior changes.

## Skills

- Create a new feature: [create-feature](.harness/skills/create-feature/SKILL.md)
- Create a new skill: [create-skill](.harness/skills/create-skill/SKILL.md)
- Check what has changed: [check-work-status](.harness/skills/check-work-status/SKILL.md)
- Open a pull request: [pull-request](.harness/skills/pull-request/SKILL.md)
- Copy to clipboard: [copy-to-clipboard](.harness/skills/copy-to-clipboard/SKILL.md)
- Copy to Slack: [copy-to-slack](.harness/skills/copy-to-slack/SKILL.md)

## Validation

Run the focused unit tests after meaningful Python changes:

```bash
python -m unittest discover -s tests -v
```
