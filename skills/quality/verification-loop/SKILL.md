---
name: verification-loop
description: "Verify each step as you go so errors are caught early, not after drift."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [quality, verification, debugging, reliability]
---

# Verification Loop

Interleave action with verification: after each consequential step, check it with
a tool before moving on. Catching an error at step *n* is far cheaper than
discovering it after ten more steps built on top of it (reasoning/implementation
"drift").

## When to Use

- Multi-step work where later steps depend on earlier ones (refactors, data
  pipelines, multi-file changes, long reasoning chains).
- Any time you're about to claim something is "done", "fixed", or "passing".

## When NOT to Use

- A single trivial step with no downstream dependency.
- Read-only Q&A where there is nothing to verify.

## Procedure

1. **State the check up front.** Before acting, decide how you'll know the step
   worked (a command, an expected output, a file that should exist/change).
2. **Act** — make the change or take the step.
3. **Verify immediately** with a tool, not by assertion:
   - Code → run tests / build / lint via `run_shell`; read the file back with
     `read_file` to confirm the edit landed.
   - Data/commands → check exit code and output; re-query the result.
   - Facts/claims → confirm against a source (`web_fetch`) or the workspace.
4. **On failure, STOP and fix** before the next step. Do not stack new work on an
   unverified result. Re-run the check after the fix.
5. **Only then proceed** to the next step, repeating the loop.
6. **Final gate:** never report success without showing the verifying evidence
   (the command output, the passing test, the diff). If you couldn't verify, say
   so explicitly.

## Output

- A short trail of step → check → result, ending in the concrete evidence that
  the work is correct (or an honest note about what remains unverified).
