---
name: docker
description: "Write, debug, and execute Dockerfiles and docker-compose configurations."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [devops, docker, containers]
---

# Docker

Create and troubleshoot Docker images and multi-container setups. Use `run_shell`
to build, run, and inspect containers. Debug layer-by-layer if builds fail.

## When to Use

- Need to containerize an application.
- Debugging a failing Docker build or runtime error.
- Setting up a local multi-service environment with compose.

## When NOT to Use

- The application is already running in production containers.
- Docker is not the right tool for the use case.

## Procedure

1. If writing a Dockerfile: clarify base image, dependencies, entry point, and
   build args.
2. Draft the Dockerfile, grouping layers to minimize rebuild time.
3. Use `run_shell` to build: `docker build -t <name> .`.
4. If build fails, read error output; pinpoint the layer; fix and rebuild.
5. Run locally: `docker run -it <name>` to verify.
6. For compose: define services, networks, and volumes in `docker-compose.yml`.
7. Use `run_shell` to start: `docker-compose up -d`.
8. Inspect logs: `docker logs <container>` or `docker-compose logs <service>`.
9. Validate health checks and inter-service communication.

## Output

```
Dockerfile created: <path>
Build result: [success|failure + error log]
Runtime test: [passed|failed + logs]
docker-compose.yml: <path> (if applicable)
```
