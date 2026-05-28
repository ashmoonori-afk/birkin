---
name: dependency-audit
description: "Find unused, outdated, and vulnerable dependencies via shell package commands."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [software-development, dependencies, security, maintenance]
---

# Dependency Audit

Identify unused, outdated, and vulnerable package dependencies to reduce bloat, improve security,
and ensure compatibility.

## When to Use

- During routine maintenance or before a major release.
- When security advisories are published for a dependency.
- When dependency tree size or build time has grown unexpectedly.

## When NOT to Use

- During active feature development (audit after feature stabilization).

## Procedure

1. **List dependencies** — Use run_shell to inspect the dependency manifest
   (e.g., `package.json`, `Pipfile`, `go.mod`, `Cargo.toml`). Use read_file to view the file.
2. **Outdated** — Run language-specific outdated check via run_shell
   (e.g., `npm outdated`, `pip list --outdated`, `cargo outdated`).
3. **Unused** — Run a static analysis tool to find unused imports via run_shell
   (e.g., `npm audit`, language linters). Read_file any flagged modules.
4. **Vulnerabilities** — Use run_shell to check for known CVEs
   (e.g., `npm audit`, `pip-audit`, `cargo audit`). Note severity and recommended upgrade.
5. **Plan removal/upgrade** — Remove unused deps by editing the manifest with write_file.
   Upgrade vulnerable deps to safe versions. Run tests via run_shell to verify no breakage.

## Output

- List of unused dependencies (with removal commands).
- List of outdated dependencies (current → recommended version).
- List of vulnerable dependencies (CVE ID, severity, fix version).
- Verification: "Audit complete → Changes applied → Tests pass."

