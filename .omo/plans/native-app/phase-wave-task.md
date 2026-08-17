# Native Application Phase-Wave-Task Plan

Status: executable work breakdown
Task size: 2-5 minutes of focused edit or verification work

## 1. Execution rules

Each task row contains:

- **D**: dependencies
- **A**: binary acceptance
- **R**: rollback
- **E**: evidence

Behavior tasks use RED-GREEN-REFACTOR. A test task captures RED before its paired production task. Each verified task receives an atomic commit.

Each wave ends with:

1. focused tests
2. real-surface QA for the wave
3. LSP diagnostics
4. specification review
5. code-quality review
6. security review when a trust boundary changed
7. cleanup receipt
8. atomic integration

## Phase 0: Baseline and plan lock

### Wave 0.1 Repository baseline

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P0W1T01 | none | Record branch, base SHA, tree, and worktree status | Exact branch/base and clean status recorded | remove note | command output |
| P0W1T02 | T01 | Enumerate current workspace/native-related tests | Test manifest names current files | remove manifest | manifest diff |
| P0W1T03 | T01 | Run focused canonical workspace suite | Existing suite exits 0 | no code change | test log |
| P0W1T04 | T01 | Run approval, memory, gateway focused suites | Existing suites exit 0 | no code change | test log |
| P0W1T05 | T01 | Run Browser, Computer Use, Office focused suites | Existing suites exit 0 | no code change | test log |
| P0W1T06 | T02-T05 | Record baseline failures separately | Every failure classified pre-existing or blocking | remove note | ledger entry |

### Wave 0.2 Plan consistency

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P0W2T01 | P0W1 | Cross-link all eight plan documents | Every link resolves | revert links | link checker |
| P0W2T02 | T01 | Verify model provenance and cross-review decisions | IDs and resolved blockers present | revert note | plan review |
| P0W2T03 | T01 | Verify no unresolved invented API remains | Every new API is scheduled or cut | revert claim | review checklist |
| P0W2T04 | T01-T03 | Commit plan documents atomically | Commit contains plans only and checks green | revert commit through normal patch | commit SHA |

## Phase 1: Protocol foundations

### Wave 1.1 Contract RED

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P1W1T01 | P0 | Add failing test for `macos` client surface | Fails on unsupported surface | delete test | RED log |
| P1W1T02 | T01 | Add `macos` surface value | T01 GREEN, old surfaces GREEN | remove value | GREEN log |
| P1W1T03 | T02 | Add failing strict envelope parse test | Fails because codec absent | delete test | RED log |
| P1W1T04 | T03 | Add protocol envelope dataclasses/parser | Strict envelope test GREEN | remove module | GREEN log |
| P1W1T05 | T04 | Add failing frame max+1 test | Fails before bound exists | delete test | RED log |
| P1W1T06 | T05 | Implement length check before allocation | Max accepted, max+1 rejected | revert frame reader | GREEN log |
| P1W1T07 | T04 | Add invalid UTF-8 and extra-key tests | Both fail for intended reasons | delete tests | RED log |
| P1W1T08 | T07 | Implement bounded UTF-8 strict decoding | Both GREEN | revert decoder | GREEN log |

### Wave 1.2 Negotiation RED-GREEN

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P1W2T01 | P1W1 | Add failing hello/ready vector test | Missing negotiation causes RED | delete test | RED log |
| P1W2T02 | T01 | Implement exact version intersection | Matching vector GREEN | revert negotiation | GREEN log |
| P1W2T03 | T02 | Add failing no-common-version test | Wrong response causes RED | delete test | RED log |
| P1W2T04 | T03 | Implement `E_PROTOCOL_VERSION` then close | Error and close observed | revert branch | transcript |
| P1W2T05 | T02 | Add failing invalid transition matrix | Illegal kind currently accepted | delete test | RED log |
| P1W2T06 | T05 | Implement connection state machine | Matrix GREEN | revert state machine | GREEN log |
| P1W2T07 | T02 | Add golden vectors for every base envelope | Python validates all vectors | remove vectors | vector test |

## Phase 2: Authentication and transports

### Wave 2.1 Capability

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P2W1T01 | P1 | Add failing mint/verify/expiry tests | Capability module absent RED | delete tests | RED log |
| P2W1T02 | T01 | Implement scoped capability record | Mint and verify GREEN | remove module | GREEN log |
| P2W1T03 | T02 | Add failing constant-time verification spy | Non-constant compare detected | delete test | RED log |
| P2W1T04 | T03 | Use constant-time comparison | Spy GREEN | revert compare | GREEN log |
| P2W1T05 | T02 | Add renewal and hard-ceiling tests | Missing lifecycle RED | delete tests | RED log |
| P2W1T06 | T05 | Implement sliding TTL and hard ceiling | Renewal and expiry GREEN | revert lifecycle | GREEN log |
| P2W1T07 | T06 | Add restart revocation test | Old token remains valid RED | delete test | RED log |
| P2W1T08 | T07 | Bind token to instance identity | Old token rejected GREEN | revert binding | GREEN log |

### Wave 2.2 Unix socket

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P2W2T01 | P2W1 | Add failing private-mode test | Insecure endpoint RED | delete test | RED log |
| P2W2T02 | T01 | Create `0700` runtime and `0600` socket | Mode test GREEN | remove server files | mode listing |
| P2W2T03 | T02 | Add wrong-peer test seam | Wrong uid not rejected RED | delete test | RED log |
| P2W2T04 | T03 | Enforce same-user peer credentials | Wrong peer rejected | revert peer check | negative log |
| P2W2T05 | T02 | Add stale/live socket tests | Missing distinction RED | delete tests | RED log |
| P2W2T06 | T05 | Implement locked connect-probe cleanup | stale removed, live preserved | revert cleanup | GREEN log |
| P2W2T07 | T02 | Add path-length and symlink tests | Unsafe path accepted RED | delete tests | RED log |
| P2W2T08 | T07 | Implement no-follow and path bound | Both rejected | revert checks | GREEN log |

### Wave 2.3 Loopback fallback

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P2W3T01 | P2W1 | Add unauthenticated loopback RED test | Request accepted or undefined | delete test | RED log |
| P2W3T02 | T01 | Bind `127.0.0.1:0` with mandatory token | Unauthenticated request rejected | revert listener | GREEN log |
| P2W3T03 | T02 | Add forged Host/Origin tests | Forged request not pinned RED | delete tests | RED log |
| P2W3T04 | T03 | Apply Host/Origin pinning | Forged requests rejected | revert pinning | GREEN log |
| P2W3T05 | T02 | Add endpoint-record mode test | Insecure record RED | delete test | RED log |
| P2W3T06 | T05 | Persist bounded endpoint metadata mode `0600` | Test GREEN, no provider token | revert record | file inspection |
| P2W3T07 | T06 | Exercise real fallback connection | hello/ready over loopback PASS | remove temp endpoint | transcript+cleanup |

## Phase 3: Workspace bridge

### Wave 3.1 Subscription and snapshots

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P3W1T01 | P2 | Add failing subscribe/snapshot test | No bridge session RED | delete test | RED log |
| P3W1T02 | T01 | Resolve WorkspaceSession and send snapshot | Snapshot matches canonical JSON | revert adapter | GREEN log |
| P3W1T03 | T02 | Add after-cursor replay test | Resume unavailable RED | delete test | RED log |
| P3W1T04 | T03 | Forward canonical events after cursor | Exact ordered events GREEN | revert subscription | event transcript |
| P3W1T05 | T04 | Add cursor-gap recovery test | Gap not detected RED | delete test | RED log |
| P3W1T06 | T05 | Emit replay-required and full snapshot | Recovery GREEN | revert gap handling | transcript |

### Wave 3.2 Commands and receipts

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P3W2T01 | P3W1 | Add failing command-forward test | Command not parsed/submitted RED | delete test | RED log |
| P3W2T02 | T01 | Parse unchanged WorkspaceCommand and submit | Accepted receipt GREEN | revert command path | receipt |
| P3W2T03 | T02 | Add duplicate/conflict tests | Idempotency missing RED | delete tests | RED log |
| P3W2T04 | T03 | Return public duplicate/conflict receipts | Same intent duplicate, mutation conflict | revert mapping | GREEN log |
| P3W2T05 | T02 | Add unsupported handler journal test | Rejection absent from journal RED | delete test | RED log |
| P3W2T06 | T05 | Route unsupported type through canonical failure | Failure event journaled | revert route | journal excerpt |
| P3W2T07 | T02 | Add actual-handler advertisement test | Declared-only list fails | delete test | RED log |
| P3W2T08 | T07 | Advertise sorted registered handlers | List equals runtime adapter handlers | revert advertisement | ready frame |

### Wave 3.3 Backpressure and heartbeat

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P3W3T01 | P3W1 | Add exact heartbeat timeout tests | Missing timer RED | delete tests | RED log |
| P3W3T02 | T01 | Implement ping/pong and peer silence close | Timers GREEN without sleeps | revert heartbeat | event-driven test |
| P3W3T03 | T02 | Add queue-overflow test | Silent loss observed RED | delete test | RED log |
| P3W3T04 | T03 | Implement desynchronized notice and pause | No silent loss | revert queue policy | transcript |
| P3W3T05 | T04 | Add slow-consumer close test | Connection never closes RED | delete test | RED log |
| P3W3T06 | T05 | Enforce bounded unwritable timeout | Close and replay recovery GREEN | revert timeout | test log |

## Phase 4: Swift protocol and transport

### Wave 4.1 Swift package and codec

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P4W1T01 | P3 | Add minimal Swift package test target | `swift test` discovers target | remove package | command output |
| P4W1T02 | T01 | Add failing Python hello-vector decode test | Missing types RED | delete test | RED log |
| P4W1T03 | T02 | Implement strict Swift envelope types | Vector GREEN | revert types | GREEN log |
| P4W1T04 | T03 | Add oversized frame decode test | Bound missing RED | delete test | RED log |
| P4W1T05 | T04 | Implement bounded Swift frame codec | Boundary GREEN | revert codec | GREEN log |
| P4W1T06 | T03 | Add all cross-language golden vectors | Python and Swift round-trip | remove vectors | vector logs |

### Wave 4.2 Swift transport

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P4W2T01 | P4W1 | Add failing connection reducer tests | Missing states RED | delete tests | RED log |
| P4W2T02 | T01 | Implement transport actor and state reducer | State transitions GREEN | revert actor | GREEN log |
| P4W2T03 | T02 | Add UDS integration test | No connection RED | delete test | RED log |
| P4W2T04 | T03 | Implement Unix socket connection | Real hello/ready PASS | revert UDS | transcript |
| P4W2T05 | T04 | Add fallback integration test | No fallback RED | delete test | RED log |
| P4W2T06 | T05 | Implement explicit loopback fallback | Visible fallback state PASS | revert fallback | screenshot+transcript |
| P4W2T07 | T06 | Add capability memory-only test | Token found persisted RED if broken | delete test | RED/GREEN log |

### Wave 4.3 Reconnect

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P4W3T01 | P4W2 | Add event-driven reconnect schedule test | Missing backoff RED | delete test | RED log |
| P4W3T02 | T01 | Implement bounded jittered reconnect | Schedule GREEN | revert reconnect | GREEN log |
| P4W3T03 | T02 | Add instance-change reset test | Old state retained RED | delete test | RED log |
| P4W3T04 | T03 | Discard projections and full replay on change | Reset GREEN | revert reset | GREEN log |
| P4W3T05 | T04 | Add capability renewal no-flicker test | UI leaves ready RED | delete test | RED log |
| P4W3T06 | T05 | Swap token atomically in memory | Ready state stable | revert renewal | UI state trace |

## Phase 5: Swift projection shell

### Wave 5.1 Canonical reducers

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P5W1T01 | P4 | Add failing snapshot reducer vector | Store absent RED | delete test | RED log |
| P5W1T02 | T01 | Implement ephemeral projection store | Snapshot vector GREEN | revert store | GREEN log |
| P5W1T03 | T02 | Add ordered-event reducer tests | Delta handling RED | delete tests | RED log |
| P5W1T04 | T03 | Reduce events by cursor | Ordered state GREEN | revert reducer | GREEN log |
| P5W1T05 | T04 | Add cursor-gap discard test | Gap patched incorrectly RED | delete test | RED log |
| P5W1T06 | T05 | Force replay state on gap | Gap test GREEN | revert behavior | GREEN log |
| P5W1T07 | T02 | Add forbidden persistence scan | Scan fails on seeded CoreData fixture | remove fixture | mutation proof |

### Wave 5.2 Window and connection UI

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P5W2T01 | P5W1 | Add UI test for title connection states | Missing view RED | delete test | RED log |
| P5W2T02 | T01 | Implement status pill and diagnostics action | All states rendered | revert view | screenshots |
| P5W2T03 | T02 | Add mutation-disabled-on-disconnect test | Control enabled RED | delete test | RED log |
| P5W2T04 | T03 | Gate mutation on ready+capability | Test GREEN | revert gate | GREEN log |
| P5W2T05 | T02 | Implement three-column adaptive shell | Empty mockup hierarchy present | revert layout | screenshot |
| P5W2T06 | T05 | Add large-text reflow test | No clipping at max size | revert reflow | screenshot |

## Phase 6: Session and conversation handlers

### Wave 6.1 Session lifecycle

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P6W1T01 | P3 | Add failing session create handler test | Unsupported RED | delete test | RED log |
| P6W1T02 | T01 | Delegate create to canonical session authority | Handler GREEN | revert handler | event receipt |
| P6W1T03 | T02 | Repeat RED-GREEN for select | Select event and snapshot change | revert handler | logs |
| P6W1T04 | T03 | Repeat RED-GREEN for rename | Index and projection update | revert handler | logs |
| P6W1T05 | T04 | Repeat RED-GREEN for compact | Canonical compact receipt | revert handler | logs |
| P6W1T06 | T02-T05 | Advertise only completed handlers | Ready list exact | revert list | ready frame |
| P6W1T07 | P3 | Add failing validated `config.set` handler test | Unsupported RED | delete test | RED log |
| P6W1T08 | T07 | Delegate `config.set` to canonical validated config authority | Requested/effective events GREEN | revert handler | event log |

### Wave 6.2 Templates

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P6W2T01 | P6W1 | Add preset contract tests for four templates | Missing records RED | delete tests | RED log |
| P6W2T02 | T01 | Define Python preset records with zero policy | Four presets GREEN | remove records | GREEN log |
| P6W2T03 | T02 | Add Swift one-shot launcher test | Radio/persistent behavior RED | delete test | RED log |
| P6W2T04 | T03 | Implement launcher and editable draft | Create+prefill, no send | revert UI | UI log |

### Wave 6.3 Conversation controls

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P6W3T01 | P3 | Add failing steer and retry handler tests | Unsupported RED | delete tests | RED log |
| P6W3T02 | T01 | Delegate steer to runtime | Real steer event GREEN | revert handler | event log |
| P6W3T03 | T02 | Implement tested retry semantics | Retry creates new intent after failure | revert handler | GREEN log |
| P6W3T04 | P5 | Add composer stream UI tests | Views absent RED | delete tests | RED log |
| P6W3T05 | T04 | Implement message stream and composer | Send/stream/complete PASS | revert views | UI video/log |
| P6W3T06 | T05 | Add code-mode payload limit test | Oversize blocked | revert code mode | UI test |
| P6W3T07 | T05 | Add Korean IME send guard | Cmd-Return ignored during composition | revert guard | IME log |

## Phase 7: Working Memory

### Wave 7.1 Python contract

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P7W1T01 | P3 | Add failing native Working Memory projection test | Missing projection RED | delete test | RED log |
| P7W1T02 | T01 | Project GoalState, fields, files evidence, revision | Mapping exact | revert projection | JSON fixture |
| P7W1T03 | T02 | Add merge schema RED tests | Missing strict payload RED | delete tests | RED log |
| P7W1T04 | T03 | Implement merge delegation and preview | Transaction GREEN | revert handler | GREEN log |
| P7W1T05 | T04 | Add clear/revision/budget tests | Missing cases RED | delete tests | RED log |
| P7W1T06 | T05 | Implement clear and canonical errors | All GREEN | revert clear | GREEN log |

### Wave 7.2 Swift surface

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P7W2T01 | P7W1 | Add five-row mapping UI test | Missing rows RED | delete test | RED log |
| P7W2T02 | T01 | Render Goals/Context/Files/Constraints/Notes | Mapping GREEN | revert view | screenshot |
| P7W2T03 | T02 | Add requested-vs-effective update test | Optimistic state RED | delete test | RED log |
| P7W2T04 | T03 | Implement preview, submit, confirming event | UI GREEN | revert editor | UI log |
| P7W2T05 | T04 | Add clear scope and budget accessibility tests | Missing copy/actions RED | delete tests | RED log |
| P7W2T06 | T05 | Implement clear sheet and canonical errors | Tests GREEN | revert sheet | screenshots |

## Phase 8: Owned Terminal

### Wave 8.1 Python PTY service

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P8W1T01 | P3 | Add failing terminal create contract test | Command unsupported RED | delete test | RED log |
| P8W1T02 | T01 | Implement `native_human` actor and Python terminal lease proposal | Required shell approval precedes lease | revert actor/lease | GREEN log |
| P8W1T03 | T02 | Implement terminal session model and create under live lease | Opened event GREEN | revert service | GREEN log |
| P8W1T04 | T03 | Add input/output sequence test | I/O missing RED | delete test | RED log |
| P8W1T05 | T04 | Implement bounded PTY input/output under lease | Echo/output GREEN | revert I/O | transcript |
| P8W1T06 | T05 | Add resize/signal/close and lease-expiry tests | Lifecycle missing RED | delete tests | RED log |
| P8W1T07 | T06 | Implement resize, process-tree signals, and lease revocation | Lifecycle GREEN | revert methods | GREEN log |
| P8W1T08 | T07 | Add reconnect screen snapshot test | Screen unavailable RED | delete test | RED log |
| P8W1T09 | T08 | Implement bounded screen snapshot | Reconnect GREEN | revert snapshot | transcript |
| P8W1T10 | T02-T09 | Run existing macOS shell acceptance | Suite remains GREEN | revert terminal wave | test log |

### Wave 8.2 Swift Terminal

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P8W2T01 | P8W1 | Add terminal output reducer test | Missing RED | delete test | RED log |
| P8W2T02 | T01 | Implement terminal projection reducer | Sequence GREEN | revert reducer | GREEN log |
| P8W2T03 | T02 | Add keyboard/input UI test | No live input RED | delete test | RED log |
| P8W2T04 | T03 | Render VT surface and send input | Real command output PASS | revert view | screenshot+transcript |
| P8W2T05 | T04 | Add interrupt/close confirmation tests | Missing controls RED | delete tests | RED log |
| P8W2T06 | T05 | Implement Python signal/close controls | Tests GREEN | revert controls | UI log |
| P8W2T07 | T06 | Run bad-input and cleanup QA | Invalid signal refused, no process remains | teardown terminal | receipt |

## Phase 9: Approvals and Activity

### Wave 9.1 Approval projections

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P9W1T01 | P3 | Add pending/risk/sealed projection test | Missing fields RED | delete test | RED log |
| P9W1T02 | T01 | Project canonical approval records | Fixture GREEN | revert projection | JSON fixture |
| P9W1T03 | T02 | Add multi-surface race test | Losing client errors RED | delete test | RED log |
| P9W1T04 | T03 | Emit normal answered-elsewhere event | One execution, resolved UI event | revert event | race log |
| P9W1T05 | T02 | Add requested/effective config projection test | Missing distinction RED | delete test | RED log |
| P9W1T06 | T05 | Project canonical policy and pending request | GREEN | revert projection | fixture |

### Wave 9.2 Approval UI and Activity

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P9W2T01 | P9W1 | Add approval card UI tests | Missing RED | delete tests | RED log |
| P9W2T02 | T01 | Implement risk cards and explicit decisions | Approve/reject PASS | revert UI | UI log |
| P9W2T03 | T02 | Add notification non-authority test | Notification emits answer RED if broken | delete test | RED log |
| P9W2T04 | T03 | Implement deep-link-only notification | Test GREEN | revert notification | automation log |
| P9W2T05 | P3 | Add append-only Activity projection test | Missing RED | delete test | RED log |
| P9W2T06 | T05 | Project receipts and integrity warnings | Fixture GREEN | revert projection | fixture |
| P9W2T07 | T06 | Add Hide read non-persistence test | Hidden state persisted RED if broken | delete test | mutation proof |
| P9W2T08 | T07 | Implement in-memory filter only | Test GREEN | revert filter | UI log |

## Phase 10: Browser, Computer Use, Office

### Wave 10.1 Surface transport

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P10W1T01 | P3 | Add surface snapshot/revision RED tests | Missing kinds RED | delete tests | RED log |
| P10W1T02 | T01 | Implement negotiated surface messages | Snapshot/revision GREEN | revert messages | transcript |
| P10W1T03 | T02 | Add surface-gap recovery test | Gap patched RED | delete test | RED log |
| P10W1T04 | T03 | Force full surface snapshot on gap | GREEN | revert recovery | transcript |
| P10W1T05 | T02 | Add seeded-secret projection test | Secret leaks RED | delete test | RED log |
| P10W1T06 | T05 | Apply canonical projection redaction | Secret absent GREEN | revert redaction | test log |

### Wave 10.2 Browser Aside

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P10W2T01 | P10W1 | Add Browser projection fixture test | Missing RED | delete test | RED log |
| P10W2T02 | T01 | Project profile generation, lease, frame, nav | Fixture GREEN | revert projection | fixture |
| P10W2T03 | T02 | Add personal-profile negative test | Unsafe path RED if present | delete test | RED log |
| P10W2T04 | T03 | Keep private profile authority only | Negative test GREEN | revert change | test log |
| P10W2T05 | T02 | Add Browser Swift UI tests | Missing RED | delete tests | RED log |
| P10W2T06 | T05 | Implement toolbar/status/frame view | Real local page PASS | revert UI | screenshot |

### Wave 10.3 Computer Use

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P10W3T01 | P10W1 | Add status projection test | Missing RED | delete test | RED log |
| P10W3T02 | T01 | Project never-prompt capability status | Fixture GREEN | revert projection | fixture |
| P10W3T03 | T02 | Add consent binding/expiry projection tests | Missing RED | delete tests | RED log |
| P10W3T04 | T03 | Project one-shot grant state and receipts | Tests GREEN | revert projection | GREEN log |
| P10W3T05 | T04 | Add Swift consent countdown test | Wrong expiry RED | delete test | RED log |
| P10W3T06 | T05 | Implement status and consent UI | J6 PASS | revert UI | action log |

### Wave 10.4 Office

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P10W4T01 | P10W1 | Add Office projection fixture test | Missing RED | delete test | RED log |
| P10W4T02 | T01 | Project inventory, docs, provenance, receipts | Fixture GREEN | revert projection | fixture |
| P10W4T03 | T02 | Add create/open jail integration tests | Missing bridge RED | delete tests | RED log |
| P10W4T04 | T03 | Delegate create/open to DocumentService | Tests GREEN | revert handlers | receipts |
| P10W4T05 | T04 | Add Swift Office UI tests | Missing RED | delete tests | RED log |
| P10W4T06 | T05 | Implement New/Open and refusal states | J5 PASS | revert UI | screenshots |

## Phase 11: Desktop integration

### Wave 11.1 Drag/drop and menu bar

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P11W1T01 | P6 | Add jailed import protocol tests | Direct path use RED | delete tests | RED log |
| P11W1T02 | T01 | Implement Python jailed import and receipt | Safe copy GREEN | revert import | receipt |
| P11W1T03 | T02 | Add drag/drop UI tests | Missing RED | delete tests | RED log |
| P11W1T04 | T03 | Implement drop states and reference chip | J8 PASS | revert UI | action log |
| P11W1T05 | P9 | Add menu bar navigation-only tests | Authority action RED if broken | delete tests | RED log |
| P11W1T06 | T05 | Implement connection/session/approval menu | Tests GREEN | revert menu | screenshots |

### Wave 11.2 Notifications and voice

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P11W2T01 | P9 | Add bounded redacted notification tests | Leak/action RED | delete tests | RED log |
| P11W2T02 | T01 | Implement deep-link notifications | Tests GREEN | revert notifications | automation log |
| P11W2T03 | P6 | Add voice capability-gate tests | Control visible incorrectly RED | delete tests | RED log |
| P11W2T04 | T03 | Implement optional push-to-talk composer input | Editable text, no auto-send | revert voice | action log |

### Wave 11.3 Supervisor recovery

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P11W3T01 | P4 | Add ownership and restart-ceiling tests | Missing RED | delete tests | RED log |
| P11W3T02 | T01 | Implement owned-bridge supervisor | User bridge untouched | revert supervisor | GREEN log |
| P11W3T03 | T02 | Add five-in-sixty crash-loop test | Infinite restart RED | delete test | RED log |
| P11W3T04 | T03 | Stop and expose bounded diagnostics | Test GREEN | revert ceiling | diagnostics |
| P11W3T05 | T04 | Exercise both-direction restart | J7 PASS, no duplicate | cleanup processes | action log |

## Phase 12: Accessibility and visual fidelity

### Wave 12.1 Accessibility

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P12W1T01 | P5-P11 | Run unlabeled-control mutation test | Seeded unlabeled control fails audit | remove fixture | mutation proof |
| P12W1T02 | T01 | Complete labels, actions, landmarks | Audit GREEN | revert labels | report |
| P12W1T03 | T02 | Run keyboard-only J1/J3 | Both complete without pointer | revert shortcut changes | action log |
| P12W1T04 | T02 | Run VoiceOver J2/J6 | Both complete | revert accessibility changes | action log |
| P12W1T05 | T02 | Run Korean IME matrix | No premature send or corruption | revert input change | QA log |
| P12W1T06 | T02 | Capture contrast/large-text/reduced-motion | No clipping, non-color status | revert styling | screenshots |

### Wave 12.2 Visual QA

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P12W2T01 | P12W1 | Capture empty reference surface | Screenshot saved | delete artifact | path |
| P12W2T02 | T01 | Capture active journey surfaces | All named panels live | delete artifact | paths |
| P12W2T03 | T01-T02 | Compare hierarchy to mockup | Review lists intentional differences | revert visual diff | report |
| P12W2T04 | T03 | Fix blocking clipping/density defects | Reviewer PASS | revert fix | before/after |
| P12W2T05 | T04 | Run CJK visual reviewer | No clipping or width drift | revert fix | verdict |

## Phase 13: Packaging and CI

### Wave 13.1 CI

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P13W1T01 | P1-P12 | Add failing CI-shape contract for native job | Missing job RED | delete test | RED log |
| P13W1T02 | T01 | Add macOS native build/test job | Contract GREEN | revert workflow | GREEN log |
| P13W1T03 | T02 | Add protocol/E2E evidence upload | Artifact present | revert step | CI artifact |
| P13W1T04 | T02 | Run Python three-OS matrix | All jobs GREEN | fix only caused failures | CI URLs |
| P13W1T05 | T02 | Run macOS native job | Job GREEN | fix only caused failures | CI URL |

### Wave 13.2 Package

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P13W2T01 | P13W1 | Build clean release app | Build exits 0 | remove build | build log |
| P13W2T02 | T01 | Inspect universal architectures | Required slices present | revert build config | `lipo` output |
| P13W2T03 | T01 | Sign nested components inside-out | codesign verify PASS | remove signed build | output |
| P13W2T04 | T03 | Verify hardened runtime and entitlements | Minimum set confirmed | revert entitlements | report |
| P13W2T05 | T04 | Build DMG and record hashes | Artifact and manifest exist | delete artifact | hashes |
| P13W2T06 | T05 | Submit notarization | Accepted result | no release | notary output |
| P13W2T07 | T06 | Staple and Gatekeeper assess | Both PASS | no release | outputs |
| P13W2T08 | T07 | Launch packaged app and run J1 | Journey PASS | teardown app/backend | action log |

## Phase 14: Documentation and final gates

### Wave 14.1 Public contracts and README

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P14W1T01 | P1-P13 | Publish stable architecture overview | Matches shipped boundaries | revert doc | review |
| P14W1T02 | T01 | Publish stable protocol contract | Matches vectors and errors | revert doc | contract test |
| P14W1T03 | T01 | Publish security boundary guide | Matches scans and tests | revert doc | review |
| P14W1T04 | T01-T03 | Update README Future Roadmap to shipped state | English accurate | revert README | cross-check |
| P14W1T05 | T04 | Update README.ko mirror | Semantic parity | revert README.ko | diff review |

### Wave 14.2 Repository gates

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P14W2T01 | P14W1 | Run native CLI `--help` | Exit 0 and accurate | fix caused defect | transcript |
| P14W2T02 | T01 | Run successful native CLI command | Expected output | teardown backend | transcript |
| P14W2T03 | T01 | Run invalid native CLI input | Nonzero bounded error | no state | transcript |
| P14W2T04 | T01-T03 | Run static security scans | No introduced blocker | fix caused findings | reports |
| P14W2T05 | T01-T04 | Run full Python suite once | GREEN | fix caused failures | log |
| P14W2T06 | T01-T04 | Run full Swift suite once | GREEN | fix caused failures | log |
| P14W2T07 | T05-T06 | Run complete packaged journey | All panels and reconnect PASS | cleanup all resources | evidence bundle |

## Phase 15: Independent review and delivery

### Wave 15.1 Final reviews

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P15W1T01 | P14 | Run goal/constraint review | Unconditional PASS | fix blockers | verdict |
| P15W1T02 | P14 | Run code-quality review | Unconditional PASS | fix blockers | verdict |
| P15W1T03 | P14 | Run security review | Unconditional PASS | fix blockers | verdict |
| P15W1T04 | P14 | Run hands-on QA review | Unconditional PASS | fix blockers | verdict |
| P15W1T05 | P14 | Run context/release review | Unconditional PASS | fix blockers | verdict |
| P15W1T06 | T01-T05 | Re-run affected evidence only | Current-tree PASS | fix regression | ledger |

### Wave 15.2 Push and PR

| ID | D | Action | A | R | E |
| --- | --- | --- | --- | --- | --- |
| P15W2T01 | P15W1 | Audit atomic commit list | Every task commit clean | repair before push | log |
| P15W2T02 | T01 | Push branch normally | Remote branch updated | no force action | push output |
| P15W2T03 | T02 | Create PR targeting main | PR URL and correct base | close PR if malformed | URL |
| P15W2T04 | T03 | Verify no auto-merge and no main push | Both forbidden states absent | disable auto-merge if present | PR state |
| P15W2T05 | T03 | Subscribe to required checks | Live monitor armed | stop monitor after terminal | monitor ID |
| P15W2T06 | T05 | Resolve introduced check failures | Required checks GREEN | revert/fix atomic commit | CI URLs |
| P15W2T07 | T06 | Verify mergeability | PR reports mergeable | resolve conflict normally | PR JSON |
| P15W2T08 | T07 | Record final completion audit | Every requirement mapped to evidence | reopen missing task | audit |

## 2. Critical path

`P1 protocol -> P2 auth/transport -> P3 bridge -> P4 Swift transport -> P5 projection shell -> P6 handlers -> P7/P8/P9 -> P10 surfaces -> P11 desktop -> P12 QA -> P13 package/CI -> P14 gates -> P15 delivery`

## 3. Stage-to-phase execution map

| Stage | Execute these waves before the stage gate |
| --- | --- |
| Stage 0 | P1-P4, P7W1T01-T02, P8W1, P10W1 |
| Stage 1 | P5, read-only P7W2T01-T02, P9W2T05-T06, and read-only Browser/Computer Use/Office projections |
| Stage 2 | P6, P8W2, P9 approval controls |
| Stage 3 | P7 mutation tasks and P10 surface controls |
| Stage 4 | P11-P13 and all P12 evidence |

Although task identifiers are grouped by domain, this table controls execution order. Read projections needed by Stage 1 move ahead of Stage 2 mutation waves.

Parallel work is allowed only where:

- write scopes are disjoint,
- no task consumes an unfinished schema,
- each child has its own branch/worktree if writing,
- the lead integrates one verified atomic unit at a time.

## 4. Completion rule

No phase is complete until:

- every task is terminal,
- all paired RED/GREEN evidence exists,
- real-surface QA passed,
- resources are cleaned up,
- wave reviews passed,
- the atomic commits are green.
