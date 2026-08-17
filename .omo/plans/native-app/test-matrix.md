# Native Application Verification Matrix

Status: normative test and evidence contract

## 1. Test discipline

Every behavior change:

1. creates a failing test at the narrowest faithful seam,
2. records RED for the intended assertion,
3. implements the smallest fix,
4. records GREEN,
5. exercises the real surface,
6. records cleanup,
7. commits atomically.

No fixed sleeps, timing luck, skipped tests, weakened assertions, or mocked-away authority boundaries.

Async tests subscribe before triggering and await exact events with bounded timeouts.

## 2. Python protocol tests

Planned files:

- `tests/test_native_protocol_codec.py`
- `tests/test_native_protocol_negotiation.py`
- `tests/test_native_protocol_security.py`
- `tests/test_native_protocol_bounds.py`
- `tests/test_native_protocol_reconnect.py`
- `tests/test_native_protocol_backpressure.py`
- `tests/test_native_bridge_workspace.py`
- `tests/test_native_surface_projections.py`
- `tests/test_native_terminal_service.py`
- `tests/test_native_supervisor.py`
- `tests/test_native_architecture_boundaries.py`

| Contract | Positive | Negative/adversarial |
| --- | --- | --- |
| frame codec | round-trip golden vectors | length bomb, partial frame, invalid UTF-8 |
| strict envelope | all message kinds | extra/missing keys, invalid transition |
| version | exact common version | no common version, post-ready mismatch |
| UDS auth | same-user success | wrong uid, insecure mode, symlink |
| loopback auth | pinned local success | no token, forged Host/Origin |
| capability | mint, renew, rotate | malformed, expired, revoked, restart reuse |
| payload bounds | max accepted | max+1, depth+1 |
| command | accepted and terminal event | unsupported, stale, conflict |
| duplicate | same intent returns receipt | same id changed payload |
| subscription | snapshot and resume | unknown session, cursor gap |
| backpressure | bounded replay recovery | queue overflow, slow consumer |
| restart | full replay on instance change | duplicate execution attempt |
| diagnostics | bounded redacted export | seeded secrets absent |

## 3. Existing Python regression suites

At minimum:

- workspace contract, journal, session protocol, runtime adapter, and E2E
- runtime and gateway
- gateway restart and progress
- Working Memory and goals
- approvals and operation approval integrity/review
- process and macOS shell acceptance
- Browser Aside service, policy, control, native E2E, and boundaries
- Computer Use schema, binding, events, approvals, cancellation, artifacts, and macOS fixtures
- all Office contract, security, path, active-content, adapter, CI, and package tests
- CI platform matrix contract

The exact list is generated from current paths before each release rather than pinning a stale subset.

## 4. Handler tests

Each new handler requires:

- strict payload parse
- advertised capability
- real authority delegation
- terminal event
- idempotent replay
- stale cursor behavior
- canonical refusal
- no optimistic UI dependency

Handlers:

- session create/select/rename/compact
- chat steer/retry
- Working Memory merge/clear
- terminal create/input/resize/signal/close
- config set

Checkpoint restore, task send/cancel, skill reload, and gateway restart are not v1 native control handlers. Existing records may remain visible in projections.

Controls are disabled when the handler is not advertised.

## 5. Surface projection tests

### Working Memory

- GoalState projection
- canonical grouping
- Files uses `files_evidence`
- preview and merge
- clear
- revision conflict
- 20,000-character budget
- no vault access

### Browser Aside

- private profile identity
- generation and lease projection
- navigation and frame revision
- stale generation recovery
- control conflict
- personal-profile refusal
- redaction

### Computer Use

- never-prompt status
- exact binding
- consent proposal and expiry
- one-shot consumption
- cancellation
- artifact reference
- raw text and bytes absent

### Office

- adapter inventory
- jailed create/open
- symlink and path-race refusal
- active-content consent
- conversion loss and provenance receipt
- no external engine

## 6. Terminal tests

- create with safe cwd
- reject jail escape cwd
- interactive input and output
- UTF-8 and Korean input
- resize
- interrupt
- terminate process tree
- exit status
- reconnect screen snapshot
- output sequence gap
- bounded output
- terminal approval wait
- `native_human` actor binding
- shell-policy approval before terminal lease when required
- terminal lease expiry and disconnect revocation
- secret input absent from diagnostics
- no profile sourcing
- cleanup leaves no process group or PTY

The existing `tests/test_macos_shell_acceptance.py` and shell smoke script remain mandatory.

## 7. Swift unit tests

Planned targets:

- `BirkinProtocolTests`
- `BirkinTransportTests`
- `BirkinProjectionTests`
- `BirkinUITests`
- `BirkinAccessibilityTests`

Coverage:

- frame and envelope golden vectors
- strict decoding
- connection state reducer
- cursor and surface revision reducers
- pending command state
- capability renewal without UI flicker
- disconnect disables mutation
- instance change clears authority projections
- unavailable capability disables controls
- no persisted authority data

## 8. Cross-language golden vectors

Python writes canonical JSON fixtures for:

- hello and ready
- snapshot
- event
- command
- receipt
- error
- surface snapshot/event
- terminal events

Swift decodes and re-encodes them.

Swift writes equivalent fixtures that Python validates.

Reducer vectors compare Swift presentation state with Python snapshot reduction for each stage's rendered panels.

## 9. macOS integration tests

Use a real Python bridge process and real Swift transport:

- UDS handshake
- loopback fallback
- full snapshot
- event stream
- command receipt
- capability expiry
- backend restart
- app reconnect
- cursor gap
- surface revision gap
- terminal lifecycle
- Browser frame reference
- Office create/open
- Computer Use status and consent

Every spawned process and socket receives a teardown task and cleanup assertion.

## 10. SwiftUI automation

Required UI cases:

- first launch
- create and select session
- each template launcher
- send, stream, steer, interrupt
- attachment and code mode
- Working Memory mapping and mutation
- terminal create/input/interrupt/close
- approval approve/reject/answered-elsewhere
- Activity filtering without deletion
- Browser navigation and unavailable state
- Office new/open/refusal
- Computer Use status/consent expiry
- disconnect/reconnect/version mismatch
- menu bar navigation
- notification deep-link without authorization
- voice-to-composer without automatic send

## 11. Accessibility QA

Automated:

- labels and actions
- focus order
- no unlabeled icon buttons
- text scaling
- contrast tokens
- status not color-only
- reduced motion

Manual:

- VoiceOver complete J2 and J6
- keyboard-only complete J1 and J3
- Korean IME in all editable fields
- high contrast screenshots
- largest accessibility text size
- terminal text navigation

Binary pass criteria are recorded per scenario.

## 12. Visual QA

Reference:

`docs/assets/birkin-native-app-roadmap.png`

Capture:

- default empty state
- active conversation
- pending approval
- terminal activity
- Browser and Office active
- disconnected
- high contrast
- large text reflow

Review:

- information hierarchy
- spacing and density
- semantic color
- border and material consistency
- clipping
- CJK text
- intentional canonical differences

Store screenshots and comparison notes under the run's evidence directory, not as undocumented temporary files.

## 13. Full journeys

| ID | Journey | Binary outcome |
| --- | --- | --- |
| J1 | first answer | message and Activity receipt complete |
| J2 | Research approval | exactly-once tool result and memory evidence |
| J3 | terminal/file change | real output, approval, diff receipt |
| J4 | Browser verification | private frame and activity artifact |
| J5 | Office document | jailed create/open and provenance receipt |
| J6 | Computer Use | status, consent, one-shot result receipt |
| J7 | restart recovery | visible replay, no duplicate execution |
| J8 | drag/drop | jailed import receipt and send |
| J9 | approval race | answered-elsewhere, one execution |

The final E2E driver executes the complete ordered product journey in one built application.

## 14. Security verification

- static import-direction test
- Swift forbidden-persistence scan
- Python static security scan
- dependency vulnerability scan
- protocol fuzz corpus
- raw socket adversarial driver
- seeded secret redaction
- app container state diff
- UDS permissions and peer identity
- loopback Host/Origin/capability
- notification authorization negative test
- personal profile negative test
- Computer Use binding/grant attacks
- Office jail and active-content attacks

## 15. Build and package gates

- Python package build and clean install
- Swift debug and release builds
- Swift tests in both configurations where relevant
- universal binary inspection
- code-sign verification
- hardened runtime verification
- notarization submit and accepted result
- staple
- Gatekeeper assessment
- launch packaged application
- run J1 and a malformed protocol case from packaged app

## 16. CI matrix

Python:

- Ubuntu / supported minimum Python
- macOS / current supported Python
- Windows / current supported Python
- existing coverage floor

macOS native:

- Swift build
- Swift unit and golden-vector tests
- Python/native integration
- UI smoke
- accessibility audit
- package dry run
- evidence upload

The workflow shape remains contract-tested.

## 17. CLI release gate

Before push:

- `--help`
- one successful native command
- one invalid native command
- relevant tests
- README and README.ko cross-check
- changed trust-boundary review
- security regressions
- available static security scan

## 18. Evidence ledger

Each criterion records:

- tree hash
- command or action
- RED output
- GREEN output
- real-surface artifact
- cleanup receipt
- reviewer result
- commit SHA

Tracked content changes invalidate prior current-tree evidence and require recapture.
