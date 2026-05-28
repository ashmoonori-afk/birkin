---
name: api-design
description: "Design a clean REST/HTTP API: resources, status codes, versioning, errors."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [api, design, rest]
---

# API Design

Design a clean, predictable REST/HTTP API: resource-based routes, appropriate
status codes, clear error responses, and a versioning strategy.

## When to Use

- When designing new endpoints or a new API service.
- Before writing the API implementation; design first, code second.
- When reviewing API changes for consistency.

## When NOT to Use

- For internal RPC-style functions (different criteria apply).

## Procedure

1. **Resources** — identify nouns (users, orders, posts). Map to paths: GET
   /users, POST /users, GET /users/:id, PUT /users/:id, DELETE /users/:id.
2. **Methods** — use GET (read), POST (create), PUT/PATCH (update), DELETE (remove).
   Match HTTP semantics; avoid GET for mutations.
3. **Status Codes** — 200 (success), 201 (created), 400 (bad request), 401
   (unauthorized), 403 (forbidden), 404 (not found), 500 (server error).
4. **Errors** — consistent envelope with status, error code, message, and details.
   Never expose stack traces or database schema.
5. **Versioning** — URL path (/v1/, /v2/) or Accept header. Document deprecation
   timeline. Design for backward compatibility early.
6. **Pagination** — for list endpoints, include limit/offset or cursor. Return
   total count and next/prev links.

## Output

- OpenAPI/Swagger spec or route table with resource, method, path, status codes.
- Error response schema with examples.
- Pagination and versioning strategy.
- Rationale for key design choices.
