# Create a feature

Use this workflow when the user asks to create or implement a new feature.

## Branch and repository controls

Use this branch flow:

```text
feature/* → develop → main
```

1. Start from the latest remote `develop` branch:

   ```bash
   git fetch origin develop
   git switch -c feature/<name> origin/develop
   ```

   Choose a short, descriptive branch name using kebab-case. Do not base new
   work on `main` or on an outdated local branch.

2. Inspect the repository instructions and current status before editing. Prefer
   the automatic read-only Git tools (`git_status`, `git_diff`, `git_log`, and
   `git_branch_list`) for inspection. Use confirmed `run_command` for Git
   mutations. Keep the feature focused and avoid unrelated changes.

3. Use Conventional Commit messages for commits:

   - `feat:` for new functionality
   - `fix:` for bug fixes
   - `chore:` for maintenance or documentation-only changes

4. After meaningful changes, run the focused test suite and any relevant
   validation commands. Review the diff and working-tree status before
   committing.

5. Commit the completed focused change with an appropriate Conventional Commit
   message.

6. Open a pull request from the feature branch into `develop`. Do not merge
   feature work directly into `main`.

## Integration and release flow

1. Wait for the test matrix and merge the feature PR into `develop`.
2. Release Please runs only after pushes to `develop` and creates a release PR:

   ```text
   release-please--branches--develop--components--harness-cli → develop
   ```

3. The release PR updates `pyproject.toml` (the single authoritative version),
   `CHANGELOG.md`, and `.release-please-manifest.json`. The same workflow
   squash-merges that PR and then creates the `vX.Y.Z` tag and GitHub Release.
   `harness.__version__` reads package metadata or `pyproject.toml`, so it
   stays in sync. Do not edit those version files by hand.
4. After `develop` contains the new version, open or merge a promotion PR from
   `develop` into `main`.
5. Promotion PRs from `develop` into `main` must use a regular merge commit.
   Never squash-merge or rebase promotion PRs; preserving branch history avoids
   future conflicts.

Do not run Release Please from feature branches or treat `main` as the
integration branch. Do not manually edit the version in `harness/__init__.py`;
`harness.__version__` is derived from package metadata or `pyproject.toml`.

## Validation

For meaningful Python changes, run:

```bash
python -m unittest discover -s tests -v
```

Before reporting completion, summarize the branch, changes, tests, and commit
status. Do not claim a commit, push, pull request, or merge happened unless the
corresponding command actually succeeded.
