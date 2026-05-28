---
name: secure-coding
description: "Review and fix code for OWASP injection, secrets, authz, and validation issues."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [security, review, owasp]
---

# Secure Coding

Review code for common security vulnerabilities: SQL/command injection, hardcoded
secrets, authorization bypasses, and missing input validation at system boundaries.

## When to Use

- Before committing code that touches authentication, database, or file operations.
- When code processes user input or external data.
- As part of standard pre-commit security gate.

## When NOT to Use

- For low-risk utility functions with no external input.
- When security review has already been performed this session.

## Procedure

1. **Secrets** — use read_file on suspected areas; grep for API keys, tokens,
   passwords. Flag any hardcoded values; recommend env vars.
2. **Input Validation** — trace user inputs from boundary (API, CLI, file, form).
   Verify schema validation or sanitization before use.
3. **Injection** — find all SQL queries, shell commands, template rendering. Flag
   string concatenation; require parameterized queries or safe builders.
4. **Authorization** — check that permission checks happen before action, not
   after; verify role/scope is enforced.
5. **Error Messages** — ensure errors don't leak system paths, database structure,
   or stack traces to clients.

## Output

- List each issue with file:line, category (Secrets / Injection / Validation /
  Authz / Errors), severity, and concrete fix.
- End with count of issues by severity and a remediation priority.
