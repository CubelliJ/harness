# Repository instructions

## Skills

- Create a new feature: [create_feature](.harness/skills/create_feature.md)
- Create a new skill: [create_skill](.harness/skills/create_skill.md)
- Check what has changed: [check_work_status](.harness/skills/check_work_status.md)

## Validation

Run the focused unit tests after meaningful Python changes:

```bash
python -m unittest discover -s tests -v
```
