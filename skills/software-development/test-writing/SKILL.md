---
name: test-writing
description: "Write focused unit and integration tests; verify coverage with run_shell."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [software-development, testing, quality]
---

# Test Writing

Write clear, focused tests for individual functions and integration points. Run tests via the
shell to verify correctness and measure coverage.

## When to Use

- When implementing a new feature (test-driven: write test first).
- When fixing a bug (write a test that reproduces the bug, then fix the code).
- When refactoring (add tests before refactoring if coverage is incomplete).

## When NOT to Use

- As a replacement for code review or design validation.

## Procedure

1. **Identify scope** — Unit tests for single functions; integration tests for APIs or workflows.
   Read related code via read_file to understand inputs, outputs, and edge cases.
2. **Write test (RED)** — Create a test that documents expected behavior. Use assertions to
   check: happy path, edge cases (empty input, null, limits), and error conditions.
3. **Run test (RED)** — Use run_shell to run the test. Confirm it fails (RED) initially.
4. **Implement (GREEN)** — Write the minimal code to make the test pass. Use write_file to
   edit source code.
5. **Run test (GREEN)** — Use run_shell to re-run. Confirm the test now passes.
6. **Refactor** — Clean up duplicated test code or add more cases. Re-run via run_shell to
   stay GREEN.
7. **Coverage** — Use run_shell to check test coverage (aim for ≥80%). Add tests for uncovered
   branches.

## Output

- Test file path and test names (e.g., `test_login_valid_credentials`).
- Coverage report (via run_shell; file/line coverage ≥80%).
- Verification: "Test written → RED → GREEN → Coverage ≥80%."

