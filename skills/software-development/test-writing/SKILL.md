---
name: test-writing
description: "Write focused unit and integration tests; verify coverage."
version: 1.0.0
author: birkin
license: MIT
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
3. **Run test (RED)** — Use the available execution tools to run the test. Confirm it fails
   (RED) initially.
4. **Implement (GREEN)** — Write the minimal code to make the test pass. Use write_file to
   edit source code.
5. **Run test (GREEN)** — Use the available execution tools to re-run. Confirm the test now
   passes.
6. **Refactor** — Clean up duplicated test code or add more cases. Re-run with the available
   execution tools to stay GREEN.
7. **Coverage** — Use the available execution tools to check test coverage (aim for ≥80%).
   Add tests for uncovered branches.

## Output

- Test file path and test names (e.g., `test_login_valid_credentials`).
- Coverage report (file/line coverage ≥80%).
- Verification: "Test written → RED → GREEN → Coverage ≥80%."

