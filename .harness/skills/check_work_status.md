# Check work status

Use this workflow when asked what has been worked on, what is currently in
progress, or what changed in the repository.

1. Check the working tree and current branch:

   ```bash
   git status --short --branch
   git branch --show-current
   ```

2. Review the branch's commits relative to `develop`:

   ```bash
   git log --oneline --decorate develop..HEAD
   ```

3. Review the full working-tree diff relative to `develop`:

   ```bash
   git diff --stat develop...HEAD
   git diff develop...HEAD
   ```

4. If `develop` is unavailable locally, report that clearly and use the best
   available local reference only after confirming it exists. Do not silently
   compare against another branch.

5. Summarize the current branch, clean or modified status, commits and files
   changed relative to `develop`, and any uncommitted changes. Do not claim
   work was committed, pushed, or merged unless Git output confirms it.
