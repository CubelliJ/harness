# Repository instructions

## Git and release flow

Use this branch flow:

```text
feature/* → develop → main
```

1. Create feature branches from the latest remote `develop`:
   ```bash
   git fetch origin develop
   git switch -c feature/<name> origin/develop
   ```
2. Make focused changes using Conventional Commit messages (`feat:`, `fix:`, or `chore:`).
3. Open a pull request from the feature branch into `develop`.
4. Wait for the test matrix and merge the feature PR into `develop`.
5. Release Please runs only after pushes to `develop` and creates a release PR:
   ```text
   release-please--branches--develop--components--harness-cli → develop
   ```
6. The release PR updates `pyproject.toml`, which is the single authoritative version source, and updates the changelog and manifest. The release PR is automatically merged after its required checks pass.
7. After the release PR is merged and `develop` contains the new version, open or merge a promotion PR from `develop` into `main`.
8. Promotion PRs from `develop` into `main` must use a regular merge commit. Never squash-merge or rebase these promotion PRs, because preserving the branch history avoids future conflicts.

Do not run Release Please from feature branches or treat `main` as the integration branch. Do not manually edit the version in `harness/__init__.py`; `harness.__version__` is derived from package metadata or `pyproject.toml`.

## Validation

Run the focused unit tests after meaningful Python changes:

```bash
python -m unittest discover -s tests -v
```
