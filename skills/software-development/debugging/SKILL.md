---
name: debugging
description: "Systematically identify root causes through reproduction, isolation, and shell-based investigation."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [software-development, debugging, troubleshooting]
---

# Debugging

Systematically isolate and fix bugs by reproducing, narrowing the scope, and examining the root cause via
logs, error messages, and shell inspection.

## When to Use

- When a feature breaks or behaves unexpectedly.
- When a test fails or a build error appears.
- To understand why a tool command succeeded or failed.

## When NOT to Use

- For design or architecture issues (use refactoring or a design critique).

## Procedure

1. **Reproduce** — Run the failing command or action consistently. Use run_shell to execute the
   exact steps. Capture output and error messages verbatim.
2. **Scope** — Is it specific to a file, function, input, or environment? Use list_files and read_file
   to examine related code. Narrow the test case as far as possible.
3. **Isolate** — Add debug output or temporary logging. Re-run with run_shell. Look for the point
   where expected behavior diverges from actual behavior.
4. **Root Cause** — Read error stack traces, logs, or related code. Run diagnostic shell commands
   (e.g., env vars, version checks, file permissions).
5. **Verify Fix** — Apply the minimal fix. Re-run the failing command via run_shell to confirm
   the bug is gone and no new issues appeared.

## Output

- Steps to reproduce (copy-paste shell commands).
- Root cause (the specific line, condition, or missing piece).
- Fix applied (before/after code snippet).
- Verification: "Reproduced → Fixed → Verified."

