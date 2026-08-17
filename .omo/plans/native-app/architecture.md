# Native Application Architecture

Status: normative implementation architecture

## 1. Context

Birkin already has Python authorities for runtime, workspace, memory, approvals, tools, Browser Aside, Computer Use, Office, audit, and recovery. The native application is a new local client, not a rewrite.

The architecture must support a real macOS product while preventing a second source of truth.

## 2. Decision summary

Build:

1. a new Python native bridge under `birkin/native/`
2. a macOS Swift package and application under `macos/`
3. a versioned bounded local protocol
4. a Python-owned terminal service
5. negotiated Python-built projections for Browser Aside, Computer Use, and Office

Do not build:

- a native database
- a native policy engine
- a native tool or shell executor
- a browser profile adapter to the user's personal profile
- provider-specific logic or token storage in Swift
- a second recovery ledger

## 3. Component boundaries

### 3.1 macOS process

`BirkinApp`

- application lifecycle
- window and menu commands
- dependency assembly

`BirkinUI`

- SwiftUI views
- accessibility labels, actions, focus, and layout
- no transport, filesystem, policy, or execution

`BirkinProjection`

- `@Observable` ephemeral projection store
- pure reducers over decoded Python snapshots and events
- pending visual intent keyed by command identifier
- no disk persistence of authority data

`BirkinProtocol`

- strict frame and envelope codecs
- generated or hand-maintained typed wire records
- protocol version and error registry
- golden vectors shared with Python

`BirkinTransport`

- Unix socket connection
- loopback fallback
- heartbeat, reconnect, backpressure, and frame bounds
- in-memory capability handling

`BirkinSupervisor`

- discovers an existing bridge
- may launch a bridge owned by this application
- bounded restart policy
- never terminates a user-managed bridge

`BirkinDesktop`

- menu bar
- notifications
- jailed drag-and-drop intent
- optional voice-to-composer input
- deep links that navigate but never authorize

`BirkinDiagnostics`

- bounded redacted in-memory ring buffer
- explicit user export
- no content, tokens, file data, or hidden execution state

### 3.2 Python bridge

`birkin/native/server.py`

- UDS and private-loopback listeners
- peer authentication
- frame bounds and connection limits
- connection lifecycle

`birkin/native/protocol.py`

- envelope parsing and strict schema validation
- error translation
- negotiation

`birkin/native/capability.py`

- mint, verify, rotate, expire, and revoke local capabilities
- constant-time comparison
- no provider credentials

`birkin/native/session.py`

- hello, ready, subscribe, and command state machine
- heartbeat and capability renewal
- command receipt delivery

`birkin/native/projection.py`

- canonical workspace snapshot and event forwarding
- redacted surface snapshots and events
- limits and surface revision handling

`birkin/native/terminal.py`

- Python-owned terminal sessions
- process group ownership
- input, resize, signals, output bounds, and receipts
- delegation to existing process primitives

`birkin/native/supervisor.py`

- private runtime directory
- single-instance lock
- endpoint and PID records
- stale endpoint cleanup

### 3.3 Existing authority

Existing modules remain authoritative and do not import `birkin.native`.

Import-direction tests enforce:

`native bridge -> canonical authority`

Never:

`canonical authority -> native bridge`

## 4. Data ownership

| Data | Owner | Native lifetime |
| --- | --- | --- |
| sessions and messages | Python workspace/runtime | ephemeral projection |
| Working Memory and goals | Python harness/goals | ephemeral projection |
| approval state | Python approval store | ephemeral projection |
| activity and receipts | Python audit stores | ephemeral projection |
| terminal process state | Python terminal service | ephemeral projection |
| Browser profile/control | Python Browser Aside | ephemeral projection |
| Computer Use consent | Python approval bridge | ephemeral projection |
| Office documents/provenance | Python Office service | ephemeral projection |
| connection capability | Python bridge | Swift memory only |
| window geometry/layout | SwiftUI | `UserDefaults` |
| selected presentation panel | SwiftUI | `UserDefaults` |
| color/appearance preference | SwiftUI | `UserDefaults` |
| diagnostics | both, redacted | bounded memory; user export only |

Static scanning rejects CoreData, SwiftData, SQLite, and authority-shaped application-support storage in the Swift tree.

## 5. Workspace integration

The bridge resolves a Python `WorkspaceSession`, then:

- obtains the canonical snapshot
- subscribes after a canonical cursor
- forwards immutable workspace events
- parses every workspace mutation through `WorkspaceCommand.parse`
- submits through `WorkspaceSession.submit`
- returns public command receipts

The bridge never:

- relaxes strict keys
- rewrites versions
- truncates and retries invalid payloads
- claims success before canonical terminal events

Actual command support is derived from registered runtime adapter handlers and advertised during `ready`.

## 6. Surface projection integration

Workspace panels do not currently contain all product surfaces.

The bridge adds a negotiated surface projection layer:

```text
surface_snapshot(surface, session_id, revision, payload)
surface_event(surface, session_id, revision, event_type, payload)
```

Each projection:

- is constructed in Python
- has a per-surface monotonic revision
- is redacted before serialization
- carries opaque references instead of bytes or secrets
- defines a full snapshot fallback on revision gaps

### Browser Aside

Projection includes:

- workspace and session identity
- profile generation
- runtime status
- control lease owner kind, epoch, and expiry
- navigation state
- redacted frame reference and revision
- canonical refusal code

Commands delegate to the Browser workspace authority with lease epoch and sequence.

### Computer Use

Projection includes:

- never-prompt capability status
- supported backend tier
- application/window opaque references
- consent proposal state and expiry
- receipt and artifact references
- redacted refusal or result summary

The native protocol capability never substitutes for the narrower Computer Use foreground grant.

### Office

Projection includes:

- adapter inventory
- jailed document identities
- create/open/convert operation status
- active-content inventory and consent state
- provenance and conversion receipt references
- canonical path refusal

All operations delegate to `DocumentService`.

## 7. Terminal architecture

The Terminal is a Python-owned service because the user requires an actual owned terminal and current workspace contracts do not provide one.

`terminal.create` carries actor kind `native_human`. Python evaluates canonical shell policy and, when required, creates a `shell` approval before returning a terminal access lease. The lease is bound to the session, actor, shell, cwd, and expiry. Interactive input is accepted only while that Python-owned lease remains live; disconnect, close, expiry, or Python policy revocation invalidates it.

### Required commands

- `terminal.create`
- `terminal.input`
- `terminal.resize`
- `terminal.signal`
- `terminal.close`

### Required events

- `terminal.opened`
- `terminal.output`
- `terminal.resized`
- `terminal.exited`
- `terminal.failed`
- `terminal.receipt`

### Invariants

- one server-generated terminal identifier per process tree
- session and capability binding on every command
- cwd constrained by existing workspace access rules
- bounded input and output chunks
- fixed terminal encoding
- no login-profile sourcing
- resize is advisory and journaled
- close and interrupt use Python process-tree handling
- reconnect requests a bounded terminal screen snapshot plus subsequent events
- terminated sessions are never resurrected
- commands with consequential effects remain subject to canonical approval and tool policy

If a true PTY implementation is unavailable on a supported environment, the capability is absent. The UI must not replace it with a local Process or a static terminal.

## 8. Sessions and templates

Session create, select, rename, and compact controls depend on real Python handlers.

Templates:

- are defined by Python preset records
- create a normal session
- prefill an editable composer draft
- may suggest Working Memory content
- never change policy, approvals, network, tools, or sandbox

No persistent template mode exists.

## 9. Working Memory

Python supplies one native presentation projection combining:

- active `GoalState`
- canonical Working Memory revision and fields
- existing file/evidence projection

The Files presentation is derived from checkpoint-backed `files_evidence`; it is not a Working Memory field.

Writes use the existing `memory.write` workspace command with a strict schema:

```json
{
  "op": "merge",
  "expected_revision": 12,
  "fields": {
    "constraints": ["..."],
    "decisions": ["..."]
  }
}
```

Clear uses:

```json
{
  "op": "clear",
  "expected_revision": 12
}
```

Python validates allowed keys, size, revision, policy, and transaction behavior. Goals are read-only until a separate goal mutation contract is introduced and tested.

## 10. Recovery

### Native app restart

- restore presentation preferences only
- reconnect
- negotiate
- fetch full projection
- continue from Python authority

### Python bridge restart

- new instance identifier
- capability revoked
- native projection discarded
- full subscribe and surface snapshot
- visible recovery notice

### Restart during command

The existing journal seals orphaned started commands as failed. The UI shows that terminal state. Retry creates a new command identifier.

### Supervisor

- owns only a bridge it launched
- maximum five restarts in sixty seconds
- after the ceiling, stop restarting and show bounded diagnostics
- no infinite retry or hidden crash loop

## 11. Accessibility architecture

- semantic panel and card landmarks
- focus model independent from visual columns
- IME composition state checked before send shortcuts
- status never conveyed by color alone
- reduced motion disables nonessential transitions
- layout reflows from three columns to panel navigation under large text
- terminal accessibility exposes bounded text snapshots and actions without mirroring secret input
- stream announcements are coalesced and polite
- approval actions require explicit activation and confirmation appropriate to risk

## 12. Packaging architecture

- Swift Package Manager project plus Xcode application target
- universal arm64/x86_64 application where dependencies permit
- hardened runtime
- minimum entitlements
- App Sandbox decision documented explicitly; disabled only where the local bridge and terminal contracts require it
- inside-out code signing
- notarized and stapled distribution image
- deterministic build manifest with Python package and app versions

## 13. Dependency order

1. canonical contract tests and import-direction gate
2. protocol codec and security primitives
3. UDS server and loopback fallback
4. handshake, capability, subscription, snapshots, and events
5. Swift codec, transport, and reducers
6. handler expansion and session lifecycle
7. Working Memory contract
8. terminal service contract
9. Browser, Computer Use, and Office projections
10. product views and journeys
11. desktop integration
12. signing, notarization, CI, and release

No Swift view depending on a new command or projection starts before its Python contract is GREEN.

The v1 native control scope does not add UI handlers for checkpoint restore, task send/cancel, skill reload, or gateway restart. Existing records for those categories may be projected, but their control surfaces remain canonical CLI/WebUI behavior until separately planned.
