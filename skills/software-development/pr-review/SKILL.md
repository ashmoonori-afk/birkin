---
name: pr-review
description: "Review a code diff for correctness, security, clarity, and alignment with codebase."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [software-development, review, quality, collaboration]
---

# PR Review

Evaluate a pull request diff for logic errors, security issues, consistency, and code quality
to guide improvements before merge.

## When to Use

- When reviewing a peer's pull request.
- Before merging a feature or fix into a shared branch.
- When evaluating external contributions.

## When NOT to Use

- For self-review (use code-review skill instead).

## Procedure

1. **Scope** — Read the PR description to understand the intent, acceptance criteria, and
   test plan. Use list_files to see which files changed.
2. **Correctness** — Read the diff carefully. Check: Do the changes implement the stated intent?
   Are edge cases handled? Do logic branches make sense? Are there off-by-one errors or type mismatches?
3. **Security** — Look for: hardcoded secrets, unvalidated inputs, SQL injection risk, insecure
   cryptography, privilege escalation. Read related code via read_file if context is needed.
4. **Clarity** — Is the code readable? Are variable/function names clear? Is error handling explicit?
   Are there comments where logic is non-obvious?
5. **Consistency** — Does it match the codebase style, patterns, and conventions? Are there
   contradictions with existing abstractions?
6. **Coverage** — Are tests adequate? Do they cover happy path, edge cases, and error conditions?
   Check if coverage meets the codebase standard (≥80%).

## Output

- Findings grouped by severity (CRITICAL / HIGH / MEDIUM / LOW), each with file:line and fix.
- Questions or suggestions for the author.
- Approval decision: "Approve" / "Request changes" / "Comment."

