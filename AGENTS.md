# Repository instructions

## Scope

This is the harness repository. Prefer investigating harness/*.py and README.md
when the task concerns harness itself; include tests/ when behavior changes.

## Skills

- Create a new feature: [create-feature](.harness/skills/create-feature/SKILL.md)
- Check what has changed: [check-work-status](.harness/skills/check-work-status/SKILL.md)
- Open a pull request: [pull-request](.harness/skills/pull-request/SKILL.md)

## Validation

Run the focused unit tests after meaningful Python changes:

```bash
python -m unittest discover -s tests -v
```

For provider, API, or external-service integrations, validate the real response
shape before implementing against it. When credentials and network access are
available, make the smallest safe live request and inspect a bounded,
redacted example. Otherwise use a captured response or fixture that reflects
observed provider behavior. Do not rely only on assumptions, documentation, or
mocked data when a small real validation is practical. Record whether live
validation was performed and any limitations in the completion summary.
