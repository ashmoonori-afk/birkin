---
name: codebase-onboarding
description: "Map an unfamiliar repository structure, dependencies, and architecture via file exploration."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [software-development, onboarding, architecture]
---

# Codebase Onboarding

Systematically explore a new or unfamiliar repository to understand its structure, build system,
key modules, and architectural patterns.

## When to Use

- When starting work on an existing project.
- When investigating a bug in unfamiliar code.
- When evaluating a codebase for adoption or integration.

## When NOT to Use

- For shallow code browsing (use this for deep understanding).

## Procedure

1. **High level** — Use list_files to explore the top-level directory structure. Look for
   `README`, `ARCHITECTURE.md`, `package.json`, `Dockerfile`, or equivalent. Read key files
   to understand project purpose.
2. **Dependencies** — Read the dependency manifest (e.g., `package.json`, `go.mod`). Note major
   frameworks, libraries, and version constraints.
3. **Entry points** — Find the main executable or server entry point (e.g., `main.py`, `index.js`,
   `cmd/app/main.go`). Use read_file to understand initialization.
4. **Core modules** — Use list_files to identify major directories (e.g., `src/`, `lib/`, `services/`).
   Read representative files to understand patterns, naming, and error handling.
5. **Build & test** — Use run_shell to run the build (`make`, `npm run build`, `cargo build`).
   Run tests via run_shell to verify a working local setup.
6. **Document** — Summarize in a brief map: entry point, major modules, dependencies, build steps.

## Output

- Directory structure map (with purpose annotations).
- Key modules and their responsibilities.
- Build/test/run commands (copy-paste ready).
- Identified architecture pattern (MVC, services, monolith, etc.).

