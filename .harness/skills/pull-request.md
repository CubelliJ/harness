# Pull request

Use this workflow when asked to create, open, or prepare a pull request.

1. Confirm the working tree and current branch:

   ```bash
   git status --short --branch
   git branch --show-current
   ```

   Preserve unrelated changes. If work is not on a `feature/*` branch, ask
   before changing branches.

2. Review the branch changes relative to `develop`:

   ```bash
   git log --oneline develop..HEAD
   git diff --stat develop...HEAD
   git diff --check
   ```

3. Run the relevant validation. For meaningful Python changes, run:

   ```bash
   python -m unittest discover -s tests -v
   ```

4. Review the final diff and commit any completed changes with a Conventional
   Commit message before opening the PR. Do not commit unrelated work.

5. Push the branch and set its upstream:

   ```bash
   git push -u origin HEAD
   ```

6. Open the PR into `develop` using GitHub CLI:

   ```bash
   gh pr create --base develop --head "$(git branch --show-current)" \
     --title "<Conventional Commit title>" \
     --body-file <pr-body-file>
   ```

   Use a body with this structure, replacing the placeholders:

   ```markdown
   ## Summary
   - <user-facing change>
   - <important implementation or documentation detail>

   ## Validation
   - `<command>`

   ## Notes
   - <breaking change, migration note, or `None`>
   ```

7. Report the PR URL and validation results. Do not claim the PR was opened
   unless the GitHub CLI command succeeds.

After opening the PR, monitor CI until every required check completes:

```bash
gh pr checks <number>
```

If any check is `pending` or still running, wait a few seconds and run the
command again. Repeat until all required checks are `pass` or a check fails.
Report failures immediately with their job URLs; do not claim CI is complete
while checks remain pending. Do not merge the PR unless the user explicitly
asks; when asked to merge into `develop`, use a regular merge commit
(`gh pr merge <number> --merge`).
