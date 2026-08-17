# Native Application Release Strategy

Status: normative staged delivery and rollback plan

## 1. Release principles

- land observable stages
- keep every stage independently reversible
- never call a phase shipped without package, tests, and release artifacts
- preserve existing Python clients
- use server-advertised capabilities for operational rollback
- keep each verified task in an atomic commit
- never force-push, push directly to main, or auto-merge

## 2. Versioning

Track:

- Python package version
- macOS application semantic version
- application build number
- local protocol name and version
- workspace protocol version
- build manifest hash

Compatibility:

- exact local protocol negotiation
- no silent downgrade
- additive capabilities within a negotiated version
- breaking schema changes require protocol-version discipline

## 3. Stage 0: protocol prerequisites

Scope:

- native surface identity
- protocol codec
- UDS transport
- private-loopback fallback
- capabilities
- bounds
- subscription and replay
- diagnostics
- handler advertisement
- terminal and surface-projection contracts

Acceptance:

- protocol adversarial matrix passes
- import direction passes
- existing workspace and web clients remain green
- malformed, oversized, unauthenticated, expired, revoked, and mismatched inputs fail safely

Rollback:

- remove or disable the native bridge entry point
- no authority schema rollback is required beyond its atomic commits

Evidence:

- RED/GREEN protocol tests
- raw-socket transcripts
- UDS permission report
- loopback negative tests
- architecture and security reviews

## 4. Stage 1: read-only foundation

Scope:

- signed development app shell
- connection state
- Sessions projection
- transcript
- status
- Working Memory projection
- Activity projection
- surface capability status
- reconnect and restart replay

Acceptance:

- real app completes the read-only subset of J1 by selecting an existing fixture session and rendering its transcript and Activity receipt, plus the restart portions of J7
- protocol log proves no mutation commands
- disconnected and version-mismatch screenshots pass
- VoiceOver and keyboard can navigate all visible data

Rollback:

- advertise read-only capabilities only
- uninstalling the app leaves Python state untouched

Evidence:

- built-app screenshots
- protocol capture
- accessibility log
- app-container diff

## 5. Stage 2: human control

Scope:

- session creation and templates
- composer
- send, steer, interrupt, retry, resume
- approvals
- Activity
- owned Terminal
- notifications for current controls

Acceptance:

- J1, J2, J3, J9 pass
- sealed operation tampering fails closed
- notification tap emits no approval answer
- terminal process cleanup passes
- multi-surface race executes once

Rollback:

- revoke Stage 2 mutation capabilities
- app visibly returns to Stage 1

Evidence:

- full action logs
- terminal transcript and cleanup
- approval receipts
- notification UI automation

## 6. Stage 3: workspace surfaces

Scope:

- Browser Aside
- Computer Use status and consent
- Office create/open
- Working Memory merge and clear

Acceptance:

- J4, J5, J6 pass
- personal profile path is impossible
- Computer Use grant expires and consumes once
- Office jail and active-content negative tests pass
- Working Memory revision and budget cases pass

Rollback:

- revoke each surface independently
- render Python-provided unavailable reason

Evidence:

- Browser frame and lease receipts
- Computer Use status/consent receipts
- Office provenance and conversion receipts
- Working Memory before/after projection

## 7. Stage 4: desktop integration

Scope:

- menu bar
- notifications
- jailed drag/drop
- optional voice
- supervision and recovery hardening
- visual fidelity
- full accessibility

Acceptance:

- J7 and J8 pass
- optional voice never sends automatically
- crash-loop ceiling works
- high contrast, large text, Korean IME, VoiceOver, and keyboard QA pass
- visual review approves intentional mockup differences

Rollback:

- independent client feature flags for menu bar, notifications, drag/drop, and voice
- core surfaces remain available

Evidence:

- action logs
- screenshots
- diagnostics export
- cleanup receipts

## 8. Production candidate

Required:

- all stages green at current tree
- Python three-OS CI green
- macOS native CI green
- complete journey in release build
- security review
- accessibility review
- visual review
- README and README.ko synchronized
- package and release notes

## 9. Signing and notarization

Build:

- clean release build
- universal binary when supported
- deterministic manifest

Sign:

- hardened runtime
- minimum entitlements
- nested components signed inside-out
- verify with `codesign --verify --deep --strict --verbose=2`

Notarize:

- submit distribution artifact with `notarytool`
- require accepted result
- staple ticket
- verify staple
- assess with Gatekeeper

Package:

- notarized DMG is the primary v1 artifact
- do not add a second installer format until a concrete distribution need exists

## 10. Repository gates

Before staging each published increment:

1. relevant CLI tests
2. CLI `--help`
3. successful CLI command
4. invalid CLI input
5. README and README.ko cross-check
6. changed trust-boundary review
7. security regressions
8. available static security scan

## 11. Commit policy

- one atomic commit per verified task
- commit only files for that task
- each commit builds and tests green
- match repository history
- include the plan path footer where required by the active workflow
- never leave a WIP commit in the final branch

Wave integration:

- review and land each wave independently
- no omnibus end commit
- conflict resolution belongs to the lead

## 12. Branch and PR

- base: `79a0b230`
- branch: `feat/native-app-implementation-20260817`
- normal push only
- PR target: `main`
- no direct push to `main`
- no force-push
- no auto-merge

PR readiness:

- full user-visible summary
- trust-boundary summary
- test and QA evidence
- screenshots
- package evidence
- rollback notes
- required checks green
- mergeable state confirmed

## 13. CI checks

Python:

- Linux
- macOS
- Windows
- coverage floor
- package install
- native shell acceptance on macOS

Native:

- Swift build
- Swift tests
- protocol vectors
- Python/native integration
- UI smoke
- accessibility audit
- package build
- security scans

Required checks must be repository-required or explicitly documented until branch protection is updated.

## 14. Adoption decision

The app becomes a recommended control surface only after:

- ten consecutive manually observed J2 sessions without protocol reset
- zero authority incidents
- approval race and restart recovery remain reliable
- accessibility study completes without critical blockers
- operator study reports the native flow is at least as clear as the CLI

No telemetry is required. Use documented manual studies and issue evidence.

## 15. Stage-to-phase mapping

| Release stage | Required implementation phases/waves |
| --- | --- |
| Stage 0 | Phases 1-4 and protocol-side prerequisites from P7W1, P8W1, and P10W1 |
| Stage 1 | Phase 5, read-only P7W1T01-T02, read-only P9W2T05-T06, and read-only surface snapshots from Phase 10 |
| Stage 2 | Phase 6, Phase 8, Phase 9, and the mutating conversation/session controls |
| Stage 3 | P7W1T03-T06, Phase 7 Swift mutation UI, and Phase 10 Browser/Computer Use/Office controls |
| Stage 4 | Phases 11-13 plus full accessibility, visual, package, and recovery gates |

## 16. Rollback hierarchy

1. disable optional desktop integration
2. revoke individual surface capability
3. revoke mutation capabilities and degrade to read-only
4. disable native bridge
5. revert the atomic wave commits

Never:

- migrate authority into Swift to preserve a feature
- retain an unsafe compatibility shim
- hide a disconnected or unavailable state

## 17. Release evidence bundle

- source tree hash
- commit list
- test logs
- CI URLs
- security scan
- accessibility report
- visual comparison
- full-journey action log
- screenshots
- cleanup receipts
- codesign output
- notarization result
- staple result
- Gatekeeper result
- package hashes
- README cross-check
- PR mergeability

## 18. Renewed-audit release amendments

The stage map below supersedes earlier conflicting maps:

| Stage | Required waves |
| --- | --- |
| Stage 0 | P1-P4 protocol/transport, P7W1T01-T02 read projection, P8W1 terminal Python contract, P10W1 surface transport, import-direction/diagnostics/CI/helper-packaging/sandbox/dependency-lock gates |
| Stage 1 | P5 shell, P7W2T01-T02 read-only Working Memory UI, P9W2T05-T06 Activity projection, read-only Browser/Computer Use/Office projections |
| Stage 2 | P6 session/conversation controls, attachment picker/import, P8W2 terminal UI, P9 approval controls and approval notifications |
| Stage 3 | Working Memory mutation and Browser/Computer Use/Office command handlers and UI |
| Stage 4 | menu bar, drag/drop affordance, optional voice, remaining notifications, recovery hardening, accessibility, visual QA, package/notarization |

CI begins with Phase 1 Python protocol checks, adds Swift checks at Phase 4, and expands per wave. Production packaging embeds the signed same-revision Python helper. A dedicated gate records the no-App-Sandbox decision, minimal hardened-runtime entitlements, dependency locks, helper discovery, version mismatch, and update failure behavior.

Atomic commits contain one verified RED→GREEN behavior pair and remain green. RED output is evidence in the ledger, not a standalone failing commit.
