---
name: refactoring
description: "Safely improve code structure and clarity while keeping tests passing."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [software-development, refactoring, maintenance]
---

# Refactoring

Improve code clarity, reduce duplication, and simplify structure without changing behavior.
Use tests as a safety net to prevent regressions.

## When to Use

- When code is hard to understand or maintain.
- When consolidating duplicated logic or breaking up large functions.
- When code violates naming conventions or patterns used elsewhere in the codebase.

## When NOT to Use

- During active feature development (refactor after features are stable).
- When tests are insufficient or missing.

## Procedure

1. **Baseline** — Ensure tests pass. Use run_shell to run the test suite and confirm
   baseline coverage (≥80%). Read the code and tests to understand scope.
2. **Plan** — Identify the specific smell (duplication, long function, unclear naming).
   Plan the refactoring steps (extract, rename, consolidate) and note which tests validate each.
3. **Refactor incrementally** — Make one small change at a time (e.g., rename one variable,
   extract one function). Use read_file and write_file to edit. Run tests via run_shell after
   each step.
4. **Verify coverage** — After all changes, confirm tests still pass and coverage is maintained.
   Use run_shell to inspect before/after coverage reports.
5. **Review** — Self-review the diff for clarity, consistency, and alignment with the codebase style.

## Output

- Before/after code snippets (for major changes).
- Test results (pass/fail for each refactoring step).
- Verification: "Tests passed → Coverage maintained → Refactoring complete."

