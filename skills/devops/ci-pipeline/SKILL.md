---
name: ci-pipeline
description: "Design and implement CI pipelines: lint, test, build, deploy stages."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [devops, ci, pipeline]
---

# CI Pipeline

Build a continuous integration workflow that validates, builds, and deploys code
automatically. Define stages for linting, testing, building, and deployment.

## When to Use

- Setting up CI for a new repository.
- Redesigning or fixing a broken pipeline.
- Enforcing code quality gates before merge.

## When NOT to Use

- Pipeline already exists and is working.
- Team does not have CD/CI infrastructure (deploy manually first).

## Procedure

1. Clarify: tech stack, test framework, deployment target, and failure behavior.
2. Design stages in order:
   - **Lint**: syntax, style, security static analysis.
   - **Test**: unit, integration, coverage thresholds.
   - **Build**: compile or package the artifact.
   - **Deploy**: push to staging/production; run smoke tests.
3. Define triggers: on push, PR, tag, or schedule.
4. Set pass/fail criteria per stage (e.g., 80% coverage required).
5. Use `run_shell` to validate scripts locally before committing.
6. Document secrets, environment vars, and service dependencies.
7. Test the pipeline end-to-end on a non-prod branch first.

## Output

```
Pipeline config: <path> (.github/workflows/*.yml, .gitlab-ci.yml, etc.)
Stages:
  1. Lint: <tools> → pass if <criteria>
  2. Test: <framework> → pass if <coverage threshold>
  3. Build: <command> → artifact: <name>
  4. Deploy: <target> → post-deploy: <smoke tests>
Triggers: <on push|PR|tag|schedule>
```
