# Native Application Security Model

Status: normative trust-boundary and release-security contract

## 1. Security goals

- preserve Python as sole authority
- authenticate every native connection
- constrain local transport exposure
- prevent replay and confused-deputy execution
- bound all untrusted input
- keep secrets and raw artifacts out of projections
- preserve existing Browser, Computer Use, Office, approval, and memory boundaries
- make security degradation visible

## 2. Assets

- provider credentials
- protocol capabilities
- session and conversation data
- Working Memory and goals
- approval records and sealed operations
- audit and receipts
- terminal process control
- Browser private profiles and control leases
- Computer Use captures, opaque references, and consent grants
- Office files, path identities, active content, and provenance
- checkpoint and recovery state

## 3. Trust zones

### Python authority

Trusted to:

- enforce policy
- execute
- persist
- audit
- recover
- redact before projection

### Native bridge

Trusted local adapter with no independent policy.

It:

- authenticates transport
- validates protocol
- forwards canonical commands
- constructs redacted projections
- enforces bounds

### SwiftUI application

Untrusted for authority decisions.

It may hold:

- ephemeral projections
- in-memory capability
- presentation preferences

It may not hold:

- provider tokens
- durable session content
- approval authority
- a native database
- hidden execution state

### Local browser content

Untrusted. It cannot reach the native bridge without the loopback capability and pinned origin.

### Imported files and documents

Untrusted. Python jail and Office security own opening, copying, inspecting, and active-content consent.

## 4. Transport threats

### Wrong local user

Defense:

- `0700` runtime directory
- `0600` socket
- same-effective-user peer credentials
- short-lived capability

### Browser-to-loopback attack

Defense:

- bind only `127.0.0.1`
- Host pinning
- Origin pinning
- capability required from first frame
- capability never stored in JavaScript-accessible state

### Socket squatting

Defense:

- no-follow checks
- locked bind
- connect probe before stale removal
- reject live duplicate instance

### Frame memory exhaustion

Defense:

- length bound before allocation
- partial-frame timeout
- depth bound
- concurrency bounds
- slow-consumer close

## 5. Authentication and capability lifecycle

The local capability:

- is random and opaque
- is scoped to bridge instance, connection, surface, and view
- lives in Swift memory only
- has a 900-second sliding TTL
- has an 8-hour connection ceiling
- uses constant-time verification
- is rotated and revoked on restart or close

The private-loopback endpoint record contains a separate one-shot bootstrap secret as a narrowly scoped disk exception:

- private file mode `0600`
- not a provider credential
- not accepted after hello
- consumed and rotated after successful exchange
- read by the client only at connection time
- exchanged for the normal in-memory capability

It proves only permission to use the local bridge.

It does not prove:

- an approval decision
- policy consent
- Computer Use foreground consent
- Browser control ownership
- Office active-content consent

## 6. Command integrity

Every workspace command retains:

- strict version
- strict keys
- bounded identifier
- user-intent command identifier
- expected cursor
- canonical payload
- native client context

Journal controls:

- duplicate replay
- mutated duplicate conflict
- concurrent cursor races
- started/completed/failed lifecycle
- restart-interrupted sealing

Consequential commands are never silently replayed after a stale cursor.

## 7. Approval boundary

Swift:

- renders pending records
- submits explicit answer commands
- waits for canonical events

Python:

- decides auto-approval
- claims exactly once
- verifies sealed operation digests
- executes or refuses
- records terminal state

Notification taps and menu actions only navigate.

Multi-surface races resolve from Python events.

## 8. Terminal boundary

Threats:

- native shell bypass
- cwd escape
- profile injection
- process orphaning
- output exhaustion
- secret echo in diagnostics

Controls:

- Python-owned terminal service only
- workspace cwd validation
- no login profile sourcing
- managed process group
- bounded I/O
- explicit signals
- terminal receipts
- no input content in diagnostics
- cleanup verification for every QA terminal
- `native_human` actor identity
- Python-issued terminal access lease bound to session, shell, cwd, and expiry
- canonical `shell` approval before lease minting when effective policy requires it

## 9. Browser Aside boundary

Controls:

- per-session private profiles
- profile generation and lock
- stale-profile cleanup
- audited control leases
- epoch and sequence validation
- redacted frame/event projection
- network policy remains Python-owned

Forbidden:

- personal profile attachment
- cookie export
- raw network bodies in projection
- native policy toggle

## 10. Computer Use boundary

Controls:

- never-prompt status probes
- exact app/process/window/page generation binding
- opaque element references
- explicit mutation permission
- one-shot foreground grant
- session, intent digest, prior receipt, and expiry binding
- content-addressed bounded artifacts
- redacted events and receipts

The local protocol capability cannot substitute for the foreground grant.

## 11. Office boundary

Controls:

- descriptor-based jail
- canonical path identity
- symlink and escape prevention
- atomic create
- adapter provenance
- active-content inventory and consent
- conversion loss receipts
- no external process engine from native UI

Swift never opens or writes Office files directly as part of authority flow.

## 12. Working Memory and memory boundary

Controls:

- scoped memory remains fail-closed
- native process does not mount vault storage
- updates use canonical field allowlist and revision
- preview and render budget run in Python
- clear affects only documented session Working Memory
- GoalState is read-only until a separate contract exists

## 13. Projection redaction

Apply canonical secret key and pattern redaction at the Python projection boundary.

Projection must exclude:

- tokens
- cookies
- credentials
- raw request text where canonical events omit it
- screenshot bytes
- Office document bytes
- terminal secret input
- operation fingerprints
- tracebacks and environment dumps

Errors and diagnostics are length-bounded.

## 14. Native persistence allowlist

Allowed in `UserDefaults`:

- window frame
- column and panel sizes
- selected presentation panel
- appearance
- accessibility presentation preferences

Forbidden:

- conversation text
- session snapshots
- Working Memory
- pending command payloads
- approval records
- audit read state
- capability tokens
- Browser frames or profile data
- Computer Use artifacts
- Office document content
- provider identity secrets

Release scanning rejects CoreData, SwiftData, SQLite, and authority-shaped application-support files.

## 15. App Sandbox and entitlements

The release must document whether App Sandbox is disabled because of:

- private local bridge management
- Python process supervision
- owned terminal PTY

Even without App Sandbox:

- hardened runtime is required
- entitlements are minimal
- no arbitrary inbound network listener exists
- loopback is opt-in fallback only
- filesystem access is still constrained by Python jail and explicit user selection

Required macOS permissions are requested only at the matching user action. Status checks do not prompt.

## 16. Supply chain and package security

- lock Python and Swift dependencies
- record versions in build manifest
- scan Python dependencies
- run static Python security scan
- run Swift static analysis
- sign every nested executable and framework inside-out
- verify hardened runtime
- notarize and staple
- verify with Gatekeeper
- retain notarization and package hashes as release evidence

## 17. Threat matrix

| Threat | Control | Required evidence |
| --- | --- | --- |
| wrong-user UDS | peer credential and modes | negative integration test |
| loopback CSRF | Host/Origin and capability | forged request test |
| length bomb | bound before allocation | raw socket test |
| version confusion | exact negotiation | mismatch transcript |
| expired capability | TTL and re-handshake | expiry E2E |
| replay | journal idempotency | duplicate test |
| mutated replay | fingerprint conflict | conflict test |
| stale cursor | canonical policy | concurrent-client test |
| native policy decision | architecture/import/static gates | source scan and review |
| notification approval | deep-link-only | UI automation |
| terminal bypass | no native Process executor | source scan and E2E |
| personal browser profile | private-profile-only service | negative test |
| Computer Use confused deputy | exact binding and grant | adversarial test |
| Office jail escape | descriptor identity | symlink/race tests |
| secret projection | boundary redaction | seeded-secret tests |
| hidden native DB | persistence allowlist scan | app-container diff |
| crash-loop | restart ceiling | supervisor E2E |

## 18. Security review gate

Every wave touching a trust boundary requires:

1. changed-boundary description
2. attacker model
3. negative tests
4. static scan
5. diff review for authority movement
6. cleanup receipt
7. reviewer approval

Release blocks on:

- any UI-originated unauthorized execution
- any provider token reaching Swift
- any personal browser profile path
- any native authority database
- any unbounded protocol allocation
- any consent or approval replay
- any skipped security test
