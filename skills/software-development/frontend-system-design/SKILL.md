---
name: frontend-system-design
description: "Design large frontend architectures through explicit constraints, trade-offs, evidence, and decision records. 프론트엔드 시스템 설계."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [software-development, frontend, architecture, system-design, 프론트엔드, 시스템설계]
    provenance:
      source: https://github.com/devkodeio/frontend-system-design
      revision: ca56b546e5f12c408a2e75b2499264aacba99065
      license: MIT
      adaptation: modified-for-birkin
---

# Frontend System Design

Design a frontend as a set of explicit decisions, not a framework shopping
list. Establish constraints first, compare viable options, and leave evidence
that another engineer can review or revisit.

This procedure is a Birkin-authored adaptation of Devkode.io's MIT-licensed
Frontend System Design Guide. It preserves the source's broad architecture
questions while correcting dated guidance and adding measurable decision
records. It does not reproduce the upstream PDF or raw checklist.

## When to Use

- Before building or materially restructuring a large web application.
- When choosing rendering, state, API, component, deployment, or ownership
  boundaries.
- When a frontend architecture proposal needs explicit trade-offs, failure
  modes, verification, and rollback criteria.
- 프론트엔드 시스템 설계, 렌더링 전략, 상태 관리 경계가 필요한 경우.

## When NOT to Use

- For visual styling, component polish, or design-token authoring.
- For a security audit; use `secure-coding`.
- For a test-plan-only request; use `test-strategy`.
- For an accessibility audit; use `a11y-audit`.
- For a reproduced defect or failing program; use `debugging`.
- For a small local component whose architecture is already established.

## Required Inputs

Collect only information that can change the decision:

- Product scope, users, business model, roadmap, and compliance constraints.
- Target devices, browsers, locations, network conditions, and accessibility
  target.
- Team ownership, delivery cadence, operational maturity, and cost limits.
- Traffic, data freshness, interactivity, SEO, offline, and real-time needs.
- Existing backend contracts, identity model, deployment topology, and
  observability.

If a missing input would select a different architecture, ask one focused
question. Otherwise state the assumption and continue.

## Procedure

### 1. Frame the decision

Read the PRD, designs, existing code, and deployment documentation with
`read_file` and `list_files`. Write:

- problem and non-goals;
- user, device, network, compliance, and organization constraints;
- happy, edge, degraded, and failure flows;
- measurable success and failure signals.

Do not select a stack before this frame exists.

### 2. Model behavior and scale

Quantify the factors that shape the architecture:

- audience size, request/event volume, payloads, and freshness;
- interaction density and latency sensitivity;
- offline, reconnection, conflict, and degraded-mode behavior;
- MVP boundary, likely growth, and build-versus-reuse choices.

Record uncertainty as a range and name the threshold that would change the
design.

### 3. Choose delivery and rendering per route

Compare CSR, SSR, SSG, streaming, and hybrid delivery for each route or
surface. Evaluate:

- crawlability and semantic content;
- personalization and freshness;
- interaction and JavaScript cost;
- device/network limits and caching;
- infrastructure, skill, and operational cost.

Mixed rendering is valid. A single mode for the whole product requires
evidence, not convenience.

### 4. Define contracts and trust boundaries

Map:

- browser, backend-for-frontend, API, third-party, and identity boundaries;
- request/response schemas, errors, cancellation, idempotency, timeouts,
  retries, rate limits, and cache behavior;
- polling, batching, SSE, WebSocket, or WebRTC by directionality, freshness,
  and recovery needs;
- server-enforced permissions separately from client visibility.

Frontend route or component hiding is user experience, never authorization.
Delegate detailed threat analysis to `secure-coding`.

### 5. Decompose ownership, routes, state, and components

Produce:

- route map and deployment boundaries;
- component/domain ownership and dependency direction;
- state inventory split into server/cache, URL, durable client, ephemeral UI,
  form, and authentication/session state;
- design-system primitives versus product-specific composition;
- storage, synchronization, invalidation, and consistency rules.

Use independently deployed frontends only when team and release autonomy
outweigh duplication, consistency, routing, and operational cost.

### 6. Design quality attributes as constraints

Give each applicable attribute a measurable target and validation channel:

- accessibility conformance and keyboard/focus/reflow checks;
- current Core Web Vitals and route-specific asset/performance budgets;
- localization, language direction, formatting, and message composition;
- privacy, consent, minimization, retention, and third-party data flow;
- browser support, progressive enhancement, and graceful degradation;
- telemetry schema, correlation, redaction, sampling, alerts, and ownership;
- security, reliability, recovery, and operability.

Do not defer these to end-stage polish.

### 7. Plan validation, release, and evolution

Define:

- unit, contract, integration, workflow, accessibility, visual, performance,
  security, and cross-browser checks at the boundaries that can fail;
- local/CI command parity and deterministic test data;
- artifact provenance, environments, approvals, flags, rollout, rollback,
  backup, and recovery verification;
- production signals, owner, revisit trigger, and cleanup date for temporary
  flags or experiments.

## Decision Record

For every material choice, return:

1. **Decision** — one sentence.
2. **Context and constraints** — facts that shape it.
3. **Options** — at least two viable choices.
4. **Criteria and evidence** — measurements, prototypes, or source facts.
5. **Choice and rejected alternatives** — why the winner is better here.
6. **Consequences and failure modes** — costs, risks, and degraded behavior.
7. **Validation** — exact tests, budgets, and real-surface checks.
8. **Owner and revisit trigger** — who reopens it and when.
9. **Rollback** — observable trigger and recovery path.

## Current Corrections

Apply current primary guidance rather than preserving dated absolutes:

- JavaScript applications can be crawled; rendering remains a route-specific
  performance and reliability trade-off.
- Permanent redirects are the correct signal for permanently moved content.
- Meta keywords are not a search-ranking mechanism.
- Current Core Web Vitals are LCP, INP, and CLS.
- Prefer current image formats and responsive sizing over JPEG 2000 defaults.
- Origins or CDNs negotiate HTTP compression; bundlers prepare assets.
- Service Workers provide the PWA request/offline lifecycle; Web Workers are a
  different primitive.
- CORS controls browser response access, not authentication or authorization.
- Use a current accessibility conformance target instead of a loose checklist.

## Output

Return a compact architecture packet:

- assumptions and material unknowns;
- user/failure flows;
- route/rendering and data/trust diagrams;
- state/component/ownership map;
- quality-attribute scorecard;
- decision records;
- test/release/telemetry/rollback plan;
- specialist hand-offs and unresolved risks.
