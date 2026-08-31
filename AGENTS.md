# Repository instructions

## Scope

This is the harness repository. Prefer investigating harness/*.py and README.md
when the task concerns harness itself; include tests/ when behavior changes.

## Skills

- Create a new feature: [create_feature](.harness/skills/create_feature.md)
- Create a new skill: [create_skill](.harness/skills/create_skill.md)
- Check what has changed: [check_work_status](.harness/skills/check_work_status.md)
- Open a pull request: [pull_request](.harness/skills/pull-request.md)

## Validation

Run the focused unit tests after meaningful Python changes:

```bash
python -m unittest discover -s tests -v
```
