# Birkin Native macOS Application Masterplan

Status: implementation contract
Base: `origin/main` at `79a0b2300cadf836f87641f7dae321b7bf043e90`
Branch: `feat/native-app-implementation-20260817`
Target: production macOS SwiftUI thin shell over the existing Python authority

## 1. Planning provenance

This plan is the synthesis of two independently authored plans and a two-way adversarial review:

- Fable 5 product plan: `claude-sdk-oauth/claude-fable-5`, task `st_01a00e27`
- Opus 5 architecture plan: `claude-sdk-oauth/claude-opus-5`, task `st_01a00e28`
- Fable review of Opus: task `st_01a00e27`, resumed cross-review epoch
- Opus review of Fable: task `st_01a00e28`, resumed cross-review epoch

Both exact models first passed a real harmless authentication probe with the exact response `PROBE_OK`. Catalog visibility was not accepted as authentication proof.

The synthesis rule is:

1. Opus is normative for transport, protocol, schema, security, testing, packaging, and dependency order.
2. Fable is normative for product behavior, states, accessibility, complete user journeys, mockup corrections, and observable staged release.
3. Existing Python code and tests override either plan.
4. No control ships enabled until Python advertises its real handler or service capability.

## 2. Product outcome

Ship a signed and notarized macOS application that provides:

- Sessions and one-shot Research, Data Analysis, Writing, and Automation launch templates
- Conversation streaming, composer, attachments, code input, steer, interrupt, retry, and resume
- Working Memory presentation for Goals, Context, Files, Constraints, and Notes
- A Python-owned Terminal with real process lifecycle, output, cancellation, and receipts
- Approvals for canonical file/command/network policy projections and pending decisions
- Append-only Activity receipts
- Private Browser Aside
- Office create and open operations
- Local-private connection status, menu bar, notifications, jailed drag-and-drop import
- Computer Use capability status and one-shot foreground consent
- Optional voice-to-composer input
- Process restart and reconnect recovery
- VoiceOver, full keyboard access, Korean IME safety, high contrast, reduced motion, and scalable layout

The complete acceptance journey is:

`session creation -> conversation -> tool/terminal -> approval/activity -> Browser/Office -> Working Memory -> disconnect/reconnect`

Every surface must be live. A static panel, placeholder handler, optimistic authority state, or mock-only journey is a release blocker.

## 3. Authority boundary

Python remains the only source of truth for:

- session and conversation lifecycle
- memory, goals, and Working Memory
- tool and terminal execution
- policy and approvals
- activity, audit, receipts, and checkpoints
- Browser Aside profiles and control leases
- Computer Use capabilities, consent, artifacts, and receipts
- Office document operations, path security, provenance, and active-content consent
- recovery and idempotency

SwiftUI may:

- render Python-provided snapshots and events
- maintain ephemeral rendering state
- persist only window geometry, panel layout, appearance, and other non-authority preferences
- send explicit versioned commands
- display bounded redacted diagnostics

SwiftUI must not:

- store a provider token or local protocol capability on disk
- attach a personal browser profile
- persist hidden execution state or a second session database
- make policy or approval decisions
- execute tools, shell commands, browser operations, Computer Use actions, or Office operations directly
- treat focus, a notification tap, a toggle position, or native process ownership as authorization

## 4. Canonical seams

The implementation extends, rather than replaces:

- `birkin/workspace/contracts.py`: protocol version, strict command parsing, bounds, cursors, identifiers
- `birkin/workspace/hub.py`: session submission and event waiting
- `birkin/workspace/service.py`: command lifecycle and snapshots
- `birkin/workspace/journal.py`: idempotency, durable events, restart-interrupted sealing
- `birkin/workspace/runtime_adapter.py`: runtime handlers and assistant streaming
- `birkin/runtime.py`: turn, steer, interrupt, and provider lifecycle
- `birkin/gateway/core.py`: conversation identity, restart, and recovery
- `birkin/approvals.py`, `birkin/operation_approval.py`, `birkin/operation_policy.py`: decisions and sealed replay
- `birkin/proc.py`: process ownership and termination
- `birkin/harness.py`, `birkin/goals.py`, `birkin/memory_scopes.py`: Working Memory and memory authority
- Browser Aside, Computer Use, and Office services

The native bridge is a new Python client adapter. Existing authority modules must not import the native bridge.

## 5. Resolved cross-review blockers

### 5.1 Terminal

The application requires a real owned Terminal. The current workspace protocol has no terminal command family or PTY event schema.

Decision:

- Add a Python-owned terminal service before any terminal UI task.
- Add versioned terminal create, input, resize, signal, and close commands.
- Add terminal opened, output, resized, exited, failed, and receipt events.
- The service owns process groups, environment, cwd validation, timeouts, cancellation, output bounds, and teardown through existing process primitives.
- SwiftUI renders VT output and sends keystrokes or explicit command input only through this service.
- The native app never spawns a second shell executor.
- Shell profile sourcing remains disabled; existing macOS shell acceptance behavior remains binding.

### 5.2 Working Memory

The mockup labels are presentation groups, not new schemas:

| Native group | Canonical authority |
| --- | --- |
| Goals | `GoalState`; read-only until a separately tested goal mutation contract exists |
| Context | `decisions`, `corrections`, and `evidence` |
| Files | existing `files_evidence` workspace projection, explicitly labeled as workspace evidence |
| Constraints | `constraints` |
| Notes | `incomplete` and `next_actions` |

Working Memory writes use an explicit Python-defined payload with operation, expected revision, and canonical fields. Clear delegates to the transactional Python clear operation. The UI does not invent whether an operation needs approval.

The existing workspace command type is `memory.write`; no second native-only Working Memory command is introduced.

### 5.3 Browser, Computer Use, and Office projections

These services are not existing `WorkspaceSnapshot` panel keys.

Decision:

- The Python native projection layer emits separately negotiated, revisioned, redacted surface snapshots and events.
- Browser projections carry private workspace identity, service generation, control lease state, frame references, navigation state, and canonical refusals.
- Computer Use projections carry never-prompt capability status, opaque element/window references, consent state, and receipt references.
- Office projections carry adapter inventory, jailed document identity, operation status, provenance, active-content consent, and receipts.
- SwiftUI consumes these projections; it never calls service internals or derives security state.

### 5.4 Handler coverage

The server advertises actual enabled commands from registered Python handlers. A native control is enabled only when its command is advertised.

Unsupported intents:

- are rejected through a journaled canonical failure
- never create an optimistic success state
- render a Python-supplied unavailable reason

### 5.5 Cursor races

Only `chat.interrupt` may automatically retry a stale cursor, preserving current canonical behavior.

All other commands:

1. refresh the projection,
2. preserve the drafted intent,
3. show an inline non-modal conflict state,
4. require explicit re-submission when the user still wants the action.

Consequential actions are never silently replayed. Capability renewal and transport reconnect may reuse the same command identifier only to recover the same already-submitted intent through journal idempotency.

## 6. Local protocol

The protocol is `birkin-local-1`, framed as:

`4-byte big-endian body length + bounded UTF-8 JSON envelope`

Required properties:

- Unix domain socket is primary.
- Same-user peer credentials and private filesystem modes authenticate the UDS peer.
- Authenticated `127.0.0.1` is the only fallback.
- Host and Origin are pinned on loopback.
- Explicit hello/ready negotiation rejects version mismatches without downgrade.
- Short-lived in-memory capabilities are minted, verified with constant-time comparison, rotated, expired, and revoked on restart.
- Loopback bootstrap uses a separate one-shot connect secret from the private `0600` endpoint record. The client reads it only at connection time; a successful hello consumes and rotates it, then exchanges it for the normal in-memory capability.
- Command payloads retain the existing 65,536-byte bound and depth bound.
- Frames, subscriptions, in-flight commands, event queues, errors, and diagnostics are independently bounded.
- Snapshots and journal events retain canonical shapes.
- Surface snapshots and events are Python-generated extension records negotiated in `ready`.
- Cursor gaps force full replay.
- Restart instance identity invalidates capabilities and native projection state.
- Attachments and binary artifacts cross only as jailed content references.

The complete normative wire contract is in `protocol.md`.

## 7. Product states

Every applicable panel must implement:

1. empty
2. loading
3. live/idle
4. streaming or executing
5. awaiting approval or consent
6. canonical error/refusal
7. disconnected/degraded
8. reconnecting/replaying
9. unavailable because the Python capability is absent

The title status is not decorative:

- `LOCAL · PRIVATE`
- `CONNECTING`
- `RECONNECTING`
- `DISCONNECTED`
- `VERSION MISMATCH`
- `BACKEND UNAVAILABLE`

Mutating controls are disabled outside the ready state.

## 8. Mockup decisions

Adopt:

- three-column information architecture
- dark native appearance
- Sessions and Working Memory left
- Conversation and Terminal center
- Approvals, Activity, Browser, and Office right
- clear empty states and visible local-private status

Correct:

- template radio controls become one-shot launch buttons
- approval toggles become requested-versus-effective Python policy projections
- Network Access maps to canonical egress policy, not an approval category
- Activity Clear becomes a non-persistent view filter reset
- Terminal trash becomes an explicit Python termination request
- Working Memory labels map to canonical fields and GoalState
- notification actions navigate but never authorize

## 9. Observable release stages

### Stage 0: protocol and authority prerequisites

Includes:

- native client surface identity
- local transport, negotiation, capabilities, bounds, and diagnostics
- journal performance prerequisite
- handler capability advertisement
- terminal contract
- surface projections

Exit:

- malformed, oversized, unauthenticated, expired, replayed, and version-mismatched traffic fails safely
- existing Python workspace, approval, gateway, Browser, Computer Use, and Office suites remain green

Rollback:

- disable the native bridge entry point; existing clients remain unchanged

### Stage 1: read-only foundation

Includes:

- real Sessions, transcript, status, Working Memory, Activity, and surface availability projections
- disconnected and reconnect behavior

Exit:

- read-only first-launch and two-direction restart journeys pass on a built app
- protocol capture shows no mutation commands

Rollback:

- revoke mutation capabilities and ship the app as read-only

### Stage 2: human control

Includes:

- session creation and templates
- conversation send, steer, interrupt, retry, and resume
- approvals and Activity
- owned Terminal
- menu and notifications for current controls

Exit:

- first-answer, Research approval, terminal/file-change, multi-surface approval race, and restart-interrupted command journeys pass

Rollback:

- server advertises Stage 1 capabilities; the app degrades visibly

### Stage 3: workspace surfaces

Includes:

- Browser Aside
- Computer Use status and consent
- Office create and open
- Working Memory mutation

Exit:

- Browser verification, Office document, Computer Use consent, and Working Memory journeys pass with receipts

Rollback:

- revoke individual negotiated surface capabilities

### Stage 4: desktop integration and production release

Includes:

- menu bar
- notifications
- jailed drag-and-drop
- optional voice
- recovery hardening
- accessibility and visual fidelity
- signing, notarization, packaging, and release checks

Exit:

- complete named journey passes in the signed build
- Python three-OS and macOS native checks are green
- security, accessibility, keyboard, IME, and visual artifacts pass review

Rollback:

- independently disable optional integrations; never hide a missing core capability

Stage 5, a future Windows/shared-shell decision, is not part of this implementation.

## 10. Development method

Every behavioral task follows:

1. identify the canonical seam
2. write the smallest failing test
3. capture RED for the right reason
4. implement the smallest production change
5. capture GREEN
6. refactor without changing behavior
7. run diagnostics and the focused suite
8. exercise the real surface
9. record evidence and cleanup
10. create one atomic commit

Every wave ends with:

- independent specification review
- independent code-quality review
- independent security review for changed trust boundaries
- current-tree evidence capture
- rollback confirmation

No later wave absorbs unverified earlier work.

## 11. Required evidence

- model authentication probe records
- RED and GREEN output for every behavior task
- Python focused tests and three-OS CI
- Swift unit, protocol-vector, integration, UI, accessibility, and IME tests
- real built-app screenshots compared with the mockup
- full keyboard and VoiceOver action logs
- happy-path and malformed-input protocol transcripts
- UDS and loopback security tests
- restart, cursor-gap, capability-expiry, and slow-consumer evidence
- Terminal, Browser, Office, Computer Use, Working Memory, approval, and Activity receipts
- package, codesign, notarization, staple, Gatekeeper, and launch evidence
- CLI `--help`, successful command, invalid input, and static security scan
- README and README.ko cross-check
- required GitHub checks and mergeability

## 12. Completion condition

The project is complete only when:

- all eight plan documents agree
- stable public contracts are published under `docs/native-app/`
- every required surface is connected to Python authority
- the complete journey passes in a real signed SwiftUI application
- all tests and review gates pass
- all runtime resources are cleaned up
- every task is represented by a clean atomic commit
- the dedicated branch is pushed without force
- a PR targeting `main` exists, required checks are green, and the PR is mergeable
- main is not directly pushed and automatic merge remains disabled
