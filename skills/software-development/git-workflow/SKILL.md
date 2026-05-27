---
name: git-workflow
description: "Create branches, write convention-compliant commits, and prepare PRs via git."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [software-development, git, version-control]
---

# Git Workflow

Manage branches, commits, and pull requests using conventional commit formats and clear PR
descriptions to enable team review and integration.

## When to Use

- When starting a new feature, fix, or refactoring task.
- Before pushing code for peer review.
- When syncing with a shared remote repository.

## When NOT to Use

- For local-only exploration (use git, but skip formality).

## Procedure

1. **Branch** — Use run_shell to create a feature branch: `git checkout -b <type>/<description>`.
   Types: feat, fix, refactor, docs, test, chore, perf, ci.
2. **Commit** — After changes, stage files and write a conventional message via run_shell:
   `git commit -m "<type>: <description>"`. Include a body if the change is complex.
3. **Review Commits** — Use run_shell to inspect your commits: `git log --oneline -10` and
   `git diff <base-branch>...HEAD` to see the full scope of changes.
4. **PR Prep** — Write a clear PR title (≤70 chars) and body with: summary, test plan, and
   TODOs. Include relevant context (what, why, how tested).
5. **Push** — Use run_shell: `git push -u origin <branch>` to push the branch and open a PR.

## Output

- Branch name and commit log (via git log).
- Commit messages (conventional format, ≤80 chars per line in body).
- PR description with test plan.
- Confirmation: "Branch created → Committed → Pushed to <remote>."

