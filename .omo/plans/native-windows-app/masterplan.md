# Birkin Native Windows Application Masterplan

Status: Phases 1-3 implemented as a development preview; Phases 4-5 planned
Branch: `feat/native-windows-app-20260824`
Target: Windows 10 22H2 and current Windows 11, x64
First deliverable: **development preview**
Overall effort: Large; Phase 1 is Short (approximately 5-8 engineer-days)

## 1. Bottom line

Build the Windows client in C# on .NET 8 with WPF. Keep it a thin, native,
command-line-buildable presentation process over the existing Python
`birkin-local-1` bridge. Use authenticated `127.0.0.1` loopback and the existing
owner-only-DACL discovery record; do not add named pipes, Windows AF_UNIX, HTTP,
or another agent runtime.

Phase 1 delivered the original read-only vertical slice: connect to a live
bridge, complete `hello -> ready -> subscribe`, and render one real
Python-produced workspace snapshot in a real WPF window. Phases 2 and 3 now add
sole-reader recovery and the core Office workflow, but the result remains a
**development preview**, never complete, shipped, or customer-ready. Evidence
was captured as private local evidence under
`.omo/evidence/native-windows-20260824/`. That tree is ignored: it is not
committed, attached to a pull request, or uploaded by remote CI, so path names
below are local evidence locators rather than repository-accessible artifacts.
This checkout also contains an admin-only `tmp-office-home` directory left by a
local test; it is local residue, not product behavior, and is not claimed clean.

## 2. UI stack decision

### Chosen: WPF on .NET 8

Use `net8.0-windows` with `UseWPF=true`, native WPF text controls, and no UI
framework wrapper. Protocol and shell projects target plain `net8.0`.

Reasons:

- The installed .NET 8.0.419 SDK builds WPF from the command line without
  Visual Studio, a Windows SDK-targeting NuGet stack, Node, Rust, or WebView2.
- WPF's native TSF/IME path and mature `TextBox` composition behavior provide
  the lowest-risk starting point for Microsoft Korean IME. Real Windows 10 and
  11 composition remains a release gate rather than an assumption.
- C# adds one team language. Tauri would add Rust, TypeScript, web layout, and a
  browser runtime to a Python + Swift repository.
- The macOS split ports cleanly by responsibility: pure protocol, shell state,
  and app/view layer. SwiftUI source is not shared, but its decomposition and
  tests are reusable architecture.
- WPF is independent of installer choice. It can be published self-contained
  and packaged by WiX as an MSI without an IDE.

### Runner-up: WinUI 3 / Windows App SDK

WinUI 3 is the runner-up because it retains C#, has modern Windows controls,
and aligns naturally with MSIX. It loses today because it adds Windows App SDK
NuGet/runtime and Windows SDK TFM requirements without improving the thin
client's first workflow.

The pre-Phase-3 switch gate is closed: none of the four required switch
conditions was established, so WPF is the implemented stack. The recorded gate
was to switch to WinUI 3 only if all of these were true:

1. A minimal unstyled WPF `TextBox` reproducibly loses, commits early, or
   corrupts Microsoft Korean IME 2-set composition on both supported Windows
   10 and Windows 11 test machines.
2. The equivalent WinUI 3 `TextBox` passes the same recorded input sequence on
   both machines.
3. The pinned WinUI project builds and runs through `dotnet` on the no-Visual-
   Studio development machine and on `windows-latest`.
4. The defect cannot be removed while retaining a native WPF text control and
   normal TSF composition events.

Aesthetics, Fluent styling, hypothetical Store distribution, or a custom WPF
control bug do not trigger a switch. If all four conditions are not established
before Phase 3, WPF is locked for the first public release.

### Rejected UI alternatives

- **Avalonia:** cross-platform rendering has no product value for a
  Windows-specific client, adds a framework dependency, and moves Korean IME
  and accessibility behavior away from the most mature native path.
- **Tauri (Rust + WebView2):** adds two languages and package ecosystems,
  duplicates web security and accessibility concerns, depends on WebView2,
  and ports less of the existing native-shell decomposition.
- **WinUI 3 as first choice:** modern appearance does not justify the extra SDK,
  deployment, and runtime surface before the office workflow exists.

## 3. Protocol placement and conformance

Implement version-1 framing, ordered strict JSON, envelopes, handshake,
connection state, capability handling, and cursor reduction in C# under
`Birkin.Native.Protocol`. Do not embed Python or generate a shared runtime
library. This matches Swift's independent `BirkinNativeProtocol` approach and
keeps the app a normal .NET process.

Python remains normative. C# and Swift consume the same Python-generated golden
artifacts. `scripts/native/generate_golden_vectors.py` produces the existing
protocol fixture; the C# test project links that exact checked-in file rather
than committing a Windows copy. The projection fixture is linked the same way.
CI regenerates both, requires a clean diff, and then requires Python, Swift, and
C# semantic and byte parity. Phase 2 adds a Python-labelled invalid-frame corpus
whose expected value is the stable error code, not prose.

A protocol change is incomplete unless generator freshness, Python tests,
Swift tests, C# tests, live Python/C# loopback, and the normative protocol docs
all pass. No client can extend envelope version 1 by convenience.

## 4. Directory and dependency decision

The root is `windows/BirkinNativeApp/`:

```text
BirkinNativeApp.sln
Directory.Build.props
Directory.Packages.props
src/
  Birkin.Native.Protocol/   # net8.0; frames, messages, projection, transport
  Birkin.Native.Shell/      # net8.0; lifecycle, presentation, command intent
  Birkin.Native.App/        # net8.0-windows; WPF startup, windows, views
 tests/
  Birkin.Native.Protocol.Tests/
  Birkin.Native.Shell.Tests/
  Birkin.Native.App.Tests/
```

The exact namespaces, directories, and module names are fixed in
`architecture.md`; Phase 1's exact file ownership is fixed in
`phase-1-slice.md`.

Dependency direction is one way:

```text
App -> Shell -> Protocol -> local Python bridge
```

Python runtime/workspace modules never import anything Windows-specific. App
has no direct authority adapter, Shell has no WPF reference, and Protocol has no
presentation dependency.

## 5. Authority and local-channel decision

Python owns sessions, Working Memory, policy, execution, approvals, consent,
terminal trees, audit, receipts, recovery, and redacted product projections.
Windows renders snapshots/events and submits versioned commands. The in-memory
projection store is a cache. Only window/pane/theme/font preferences may be
persisted; no product data, capability, approval, receipt, terminal input, or
bootstrap secret may be written by the client.

Windows uses raw AF_INET on `127.0.0.1` plus the existing one-shot secret in the
owner-only-DACL discovery record. The target-machine execution already proved
that the listener runs unchanged and that both discovery directory and record
grant Full Control only to the current account. The client consumes the
`listening` stdout announcement, pins loopback, validates the record, exchanges
the secret in hello, then keeps the connection capability in memory.

Rejected channels:

- **Named pipe:** CPython has no server; a ctypes `CreateNamedPipeW` accept loop
  adds risk and no boundary stronger than the proven protected record.
- **Windows AF_UNIX:** the current UDS path and peer-UID checks are POSIX-only,
  and Windows AF_UNIX adds compatibility work without product benefit.
- **HTTP/WebSocket:** the protocol is already bounded raw framing and requires
  neither Host nor Origin semantics.

The client never interprets an external announcement PID as ownership. Attach
never kills. A supervisor can stop only the exact `IBridgeProcess` returned by
its injected spawn closure; five owned exits in a rolling 60 seconds enter a
stopped state. Shutdown disposes the session/connection before stopping that
owned process. Reconnect, gap, desynchronization, heartbeat loss, and disconnect
immediately revoke mutation authority; a replacement snapshot ends one gated
canonical replay episode.

Terminal and Browser regions are visibly present because the user directly
requested the Windows mockup hierarchy. They are truth-telling placeholders,
not omitted controls: Terminal reports unavailable until Python owns a tested
ConPTY `CreatePseudoConsole` backend, and Browser renders only canonical
projected data without inventing navigation authority. The client never starts
a local shell or a browser authority itself.

## 6. Phasing and waves

### Phase summary

| Phase | Label | Goal | Exit |
| --- | --- | --- | --- |
| 1 | Development preview (complete) | Real bridge, handshake, initial Python snapshot, real WPF window. | Private local deterministic live-window evidence was captured at `.omo/evidence/native-windows-20260824/p1-06-green.txt`; it is not a repository artifact. |
| 2 | Resilient foundation (complete) | Protocol hardening, sole-reader replay/reset, capability lifecycle, supervisor policy, and CI definition. | Focused recovery and lifecycle regressions pass; CI execution is not implied. |
| 3 | Core Office workflow development preview (complete) | Conversation + jailed files + read-only comparison/diff + canonical approval display; comparison-report save remains deferred. | Deterministic fast regressions pass while direct report save stays unavailable until Python exposes a durable multi-artifact Office job. |
| 4 | Windows beta quality (planned) | Sessions, Working Memory, Activity, desktop navigation, Korean IME, accessibility, and customer-OS evidence. | Windows 10/11 IME, keyboard, Narrator, scaling, and reconnect gates must pass. |
| 5 | Signed release candidate (planned) | Frozen Python authority, signed x64 MSI, upgrade/uninstall, installed workflow. | Clean-machine signed installed journey must pass without repo, uv, or host Python. |

Phase 1 is specified file-by-file in `phase-1-slice.md`. Its six units are
pairwise disjoint, each captures RED before production, and each has an exact
PowerShell command. None touches `birkin/native/serve.py`.

### Phase 2 implementation record: resilient foundation

The table preserves the original failing-first ownership plan, not a current
file inventory or a claim that GitHub ran it. Current evidence is the focused
Protocol/Shell coverage, sole-reader `BridgeSession` tests, and the locally
validated W7 workflow contract described in `test-matrix.md`.

| Wave/unit | Exclusive source scope | RED before production | Exact verification |
| --- | --- | --- | --- |
| P2-01 projection replay | Edit `Protocol/Projection/NativeProjectionState.cs` and `NativeProjectionStore.cs`; create `NativeProjectionReducer.cs`, `NativeProjectionSubscription.cs`, `NativeReconnect.cs`; create matching `Protocol.Tests/Projection/{NativeProjectionEventTests,NativeProjectionGapTests,NativeInstanceChangeTests,NativeSurfaceProjectionTests,NativeReconnectTests}.cs`. | Add tests first; gap vector must fail because event reduction/replay status is absent. | `dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Protocol.Tests\Birkin.Native.Protocol.Tests.csproj -c Debug --filter "FullyQualifiedName~NativeProjection|FullyQualifiedName~NativeReconnect"` |
| P2-02 capability and connection lifecycle | Edit `Protocol/Transport/NativeClientConnection.cs` and `Protocol/Messaging/NativeHandshake.cs`; create tests `Protocol.Tests/Transport/{NativeCapabilityRenewalTests,NativeHeartbeatTests,NativeConnectionReconnectTests,NativeStreamDesynchronizedTests}.cs`. | Add tests first; renewal/disconnect must fail because the old capability remains live or replay is not requested. | `dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Protocol.Tests\Birkin.Native.Protocol.Tests.csproj -c Debug --filter "FullyQualifiedName~NativeCapability|FullyQualifiedName~NativeHeartbeat|FullyQualifiedName~NativeConnectionReconnect|FullyQualifiedName~NativeStreamDesynchronized"` |
| P2-03 supervisor policy | Create `Shell/Lifecycle/{IBridgeProcess,BridgeAttachment,BridgeSupervisor}.cs` and `Shell.Tests/Lifecycle/{BridgeAttachmentTests,BridgeSupervisorTests}.cs`. | Add tests first; missing supervisor is RED. Cases include external untouched, only returned process stopped, and fifth exit at the injected 60-second boundary. | `dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Shell.Tests\Birkin.Native.Shell.Tests.csproj -c Debug --filter "FullyQualifiedName~BridgeAttachmentTests|FullyQualifiedName~BridgeSupervisorTests"` |
| P2-04 negative cross-language vectors | Edit `scripts/native/generate_golden_vectors.py`, `scripts/native/native_vector_catalogue.py`, and `Protocol.Tests.csproj`; create `macos/.../GoldenVectors/native-protocol-invalid-vectors.json`, Swift `NativeNegativeGoldenVectorParityTests.swift`, and C# `Framing/NativeNegativeGoldenVectorParityTests.cs`. | Add both client tests and fixture link first; RED is the missing generated invalid fixture. | `uv run --frozen python scripts/native/generate_golden_vectors.py; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Protocol.Tests\Birkin.Native.Protocol.Tests.csproj -c Release --filter "FullyQualifiedName~NativeNegativeGoldenVectorParityTests"` |
| P2-05 Windows CI | Create `.github/workflows/native-windows.yml` and `tests/test_native_windows_ci_contract.py`. | Add the machine-consumed workflow contract test first; RED is missing workflow/jobs, not YAML prose. | `uv run --frozen pytest -q tests/test_native_windows_ci_contract.py` |

P2-01, P2-02, and P2-03 execute in order so each RED compiles against a stable
dependency graph. P2-04 and P2-05 then run in parallel with disjoint
script/fixture versus workflow/pytest scopes. The phase gate is:

```powershell
uv run --frozen pytest -q tests/test_native_windows_import.py tests/test_native_windows_ci_contract.py
dotnet test .\windows\BirkinNativeApp\BirkinNativeApp.sln -c Release
```

The Windows Python workflow deselects only the two POSIX symlink-privilege tests
named in `test-matrix.md`; Ubuntu and macOS continue to require them. There is
no attempt to change their UDS behavior.

### Phase 3 implementation record: core Office workflow preview

The table preserves the original decomposition. Current exit evidence is the
provider-free deterministic production-composed window seam plus the separate
one-time real-provider proof described below; table commands alone are not
phase-exit evidence.

| Wave/unit | Exclusive source scope | RED before production | Exact verification |
| --- | --- | --- | --- |
| P3-01 command and receipt wire path | Create `Protocol/Messaging/NativeCommandRequest.cs`; edit `Protocol/Transport/NativeClientConnection.cs`; create `Protocol.Tests/Messaging/{NativeCommandRequestTests,NativeReceiptTests,NativeStaleCursorTests}.cs`. | Add tests first; RED is absent stable-ID/expected-cursor serialization and receipt correlation. | `dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Protocol.Tests\Birkin.Native.Protocol.Tests.csproj -c Debug --filter "FullyQualifiedName~NativeCommandRequestTests|FullyQualifiedName~NativeReceiptTests|FullyQualifiedName~NativeStaleCursorTests"` |
| P3-02 shell office-workflow state | Create `Shell/Commands/{ConversationCommands,ImportCommands,ApprovalCommands,OfficeCommands}.cs` and `Shell/Presentation/{MutationAvailability,OfficeWorkflowPresentation}.cs`; edit `Shell/ShellCoordinator.cs` and `Shell/Presentation/ShellPresentationModel.cs`; create matching files under `Shell.Tests/Commands/` and `Shell.Tests/Presentation/OfficeWorkflowPresentationTests.cs`. | Add tests first; RED requires disabled unadvertised controls, preserved stale-cursor drafts, and no optimistic approval/save success. | `dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Shell.Tests\Birkin.Native.Shell.Tests.csproj -c Debug --filter "TestCategory=OfficeWorkflow"` |
| P3-03 visible workflow and real journey | Create App views `ConversationView`, `ImportView`, `ApprovalView`, `OfficeView`, and `DiffView` (`.xaml` and `.xaml.cs` each); edit `MainWindow.xaml` and `.cs`; create App tests with the same view names, `Journeys/OfficeWorkflowJourneyTests.cs`, and fixtures `Fixtures/Office/{baseline.xlsx,candidate.xlsx,report-template.docx}`. | Add view and journey tests plus binary fixtures first; RED is missing bindings/actions, not provider availability. Then implement the views and wiring. | `dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.App.Tests\Birkin.Native.App.Tests.csproj -c Release --filter "TestCategory=OfficeWorkflow"` |

These units are sequential because each consumes the previous public surface;
their write scopes are still disjoint. The deterministic PR tests use the real
codec and reducer. The workflow defines a dispatch-only phase-exit job intended
for a protected Windows runner with an existing-account provider and the
standard live bridge, not an alternate test authority. No protected-runner or
remote workflow execution is claimed; the recorded passing provider proof was
run locally with this same filter:

```powershell
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.App.Tests\Birkin.Native.App.Tests.csproj -c Release --filter "TestCategory=OfficeWorkflow&TestCategory=ExistingAccountProvider"
```

The implemented journey imports jailed files, asks Birkin to compare the two
spreadsheets, and verifies that the read-only Diff is visible. Generic approval
controls answer only canonical Python approval records. Direct comparison-report
save remains visibly unavailable because the current durable Office job schema
cannot seal both source documents, the template, and the normalized diff in one
proposal. The protected provider gate exercises this same bounded journey and
does not claim structural report output. Fast regression is deliberately separate: the
`DeterministicWindow` tests use production composition, real WPF, the real
codec/reducer, and a real Python bridge but no provider. Tests compare sentinel
cell/document values, paths, command IDs, cursors, and receipts; they do not pin
prompt prose.

### Phase 4 waves: Windows beta quality

| Wave/unit | Exclusive source scope | RED before production | Exact verification |
| --- | --- | --- | --- |
| P4-01 Korean composition and accessibility | Create `App/Accessibility/TextCompositionGuard.cs`; edit `App/Views/ConversationView.xaml` and `.cs`; create `App.Tests/Accessibility/{TextCompositionGuardTests,KoreanCompositionTests,AccessibilityMetadataTests}.cs`. | Add tests first; RED demonstrates Enter submits during active composition and required automation metadata is absent. | `dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.App.Tests\Birkin.Native.App.Tests.csproj -c Release --filter "TestCategory=WindowsQuality"` |
| P4-02 desktop navigation without authority | Create `Shell/Presentation/DesktopIntegration.cs`, `App/Startup/DesktopMenu.cs`, `App/Startup/ApprovalNotification.cs`, and corresponding Shell/App tests. | Add tests first; RED proves notification activation can currently reach an approval action instead of navigation only. | `dotnet test .\windows\BirkinNativeApp\BirkinNativeApp.sln -c Release --filter "TestCategory=DesktopIntegration"` |
| P4-03 sessions, Working Memory, and Activity | Create `Shell/Commands/SessionCommands.cs`, `Shell/Presentation/{WorkingMemoryPresentation,ActivityPresentation}.cs`, App `Views/{SessionView,WorkingMemoryView,ActivityView}.xaml` plus code-behind, and same-named tests; edit `ShellPresentationModel.cs` and `ShellCoordinator.cs`. | Add tests first; RED is missing canonical rendering and capability-gated session intent, not expected text copy. | `dotnet test .\windows\BirkinNativeApp\BirkinNativeApp.sln -c Release --filter "TestCategory=WorkspacePresentation"` |
| P4-04 customer-OS evidence runner | Create `scripts/native/run_windows_client_quality_gate.ps1` and `tests/test_native_windows_quality_gate_contract.py`. | Add contract test first; RED is missing machine-readable OS/app/IME/scale/evidence fields. | `uv run --frozen pytest -q tests/test_native_windows_quality_gate_contract.py` |

P4-01 and P4-02 execute in order so simultaneous RED files cannot break the
shared App test project. P4-03 follows because it edits the presentation model;
P4-04 runs in parallel with P4-03 because it owns only a Python contract test
and the evidence script.

The planned hardware gate would execute on Windows 10 22H2 and current Windows
11:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\native\run_windows_client_quality_gate.ps1 -Configuration Release
```

It records app hash, OS build, Microsoft Korean IME profile, display scale,
keyboard/Narrator scenario results, and reconnect result as machine values.
Synthetic CI composition events do not replace this gate.

Computer Use and voice are not part of this preview. Terminal and Browser are
visible truth-telling placeholders solely because the user directly requested
the mockup hierarchy; they do not claim unavailable authority. Office is active
because it is part of the Phase 3 workflow.

### Phase 5 waves: signed MSI release candidate

| Wave/unit | Exclusive source scope | RED before production | Exact verification |
| --- | --- | --- | --- |
| P5-01 self-contained app and frozen bridge | Create `scripts/native/{package_windows.ps1,generate_windows_bridge_manifest.py}` and `tests/test_native_windows_bridge_package.py`; generated output is only under `dist/native-windows/`. | Add package test first; RED is missing helper manifest/self-contained files. | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\native\package_windows.ps1 -Configuration Release -UnsignedDevelopment; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; uv run --frozen pytest -q tests/test_native_windows_bridge_package.py` |
| P5-02 WiX x64 MSI | Create `windows/BirkinNativeApp/packaging/{Birkin.Native.Installer.wixproj,Package.wxs,Files.wxs,Upgrade.wxs,License.rtf}` and `tests/test_native_windows_msi_contract.py`. | Add MSI contract first; RED is missing product/upgrade/install records. | `dotnet build .\windows\BirkinNativeApp\packaging\Birkin.Native.Installer.wixproj -c Release; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; uv run --frozen pytest -q tests/test_native_windows_msi_contract.py` |
| P5-03 signing and release manifest | Create `scripts/native/{sign_windows.ps1,verify_windows_signature.ps1}` and `tests/test_native_windows_signing_contract.py`. | Add signing contract first; RED is unsigned PE/MSI and absent timestamp/manifest. | `uv run --frozen pytest -q tests/test_native_windows_signing_contract.py` |
| P5-04 installed journey | Create `windows/BirkinNativeApp/tests/Birkin.Native.App.Tests/Journeys/InstalledOfficeWorkflowJourneyTests.cs` and `.github/workflows/native-windows-release.yml`. | Add installed test first; RED is no installed app/helper and no release workflow. | `dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.App.Tests\Birkin.Native.App.Tests.csproj -c Release --filter "TestCategory=InstalledOfficeJourney"` |

P5-01, P5-02, P5-03, and P5-04 execute in order: package output is a real
input to MSI authoring, signing, and the installed journey. Their source scopes
remain disjoint for ownership and review. No packaging unit starts before the
Phase 3 workflow and Phase 4 quality gates are green.

## 7. Test matrix decision

The detailed matrix and actual W7 workflow commands are normative in
`test-matrix.md`. Workflow definition is proven by
`tests/test_native_windows_ci_contract.py`; GitHub execution is not.

- Python authority and loopback tests run on Ubuntu, macOS, and Windows.
- POSIX UDS/peer-UID tests run on Ubuntu and macOS only.
- Protocol and Shell C# tests run on all three hosted OSes to keep WPF out.
- WPF, live bridge, and MSI tests run on `windows-latest`.
- Swift remains macOS-only.
- Python generates protocol/projection fixtures; Swift and C# consume and
  byte-round-trip them; a live C# journey talks to the real Python bridge.
- The Windows Python job deselects exactly the two UDS symlink tests named in
  `test-matrix.md`; both remain mandatory on Unix.
- The dispatch-only provider job requires an externally provisioned protected
  environment and matching authenticated self-hosted runner. Neither
  provisioning nor a remote job run is proven by repository evidence.
- Current one-shot-secret, owner-only Python discovery is authenticated and
  proven. Handle-level final-path, reparse/owner, and protected-DACL verification
  in the C# discovery reader is deferred LOW hardening.
- Async tests await pre-subscribed signals with deadlines. Fixed sleeps and
  polling are forbidden.

## 8. Installer, signing, and update outline (unimplemented Phase 5)

There is currently no installer/MSI, signing, updater, packaged Windows app, or
customer-ready release. The planned first public Windows artifact is a WiX
Toolset v4 x64 MSI, not MSIX and not NSIS. WiX is pinned at 4.0.6 and built
with `dotnet`, so no Visual Studio IDE would be required. The planned package would install per user under
`%LocalAppData%\Programs\Birkin`, require Windows 10 22H2 or later, and include:

- a self-contained `win-x64` WPF publish (no machine .NET dependency);
- a PyInstaller one-folder frozen Python bridge and locked dependencies;
- checksum-pinned runtime resources needed by the core Office/provider journey;
- a signed manifest containing package version, source revision, architecture,
  lock hashes, and every helper/resource hash.

One-folder freezing is chosen over one-file extraction to avoid an extraction
parent, startup races, and antivirus-sensitive temporary executables. The app
launches only the verified serving executable returned by its spawn closure.
The planned installed workflow would not consult a repository, uv, host Python,
browser cache, or developer bridge override.

The planned MSI would have a stable UpgradeCode, versioned ProductCode,
monotonic major-upgrade rules, downgrade refusal, rollback, repair, and complete
uninstall. Updates would be signed full MSI major upgrades delivered through
the release HTTPS endpoint, WinGet, or customer IT tooling. The first public
release would have no privileged background updater or bespoke self-update
service.

Planned signing is inside-out: every shipped `.exe` and `.dll` would be
Authenticode signed; `bridge-helper.json` would receive a detached CMS
signature; the app would verify both before launch; and the enclosing MSI would
be Authenticode signed last. Public release would require a stable publisher
identity, an OV/EV code-signing certificate held in an HSM or Azure Trusted
Signing account, credentialed CI, RFC 3161 timestamping, and a release runner
with Windows SDK `signtool` plus .NET `SignedCms`. Unsigned output would be
labelled development-only and excluded from the release channel.

MSIX is rejected for the first release because package identity and App
Installer updates do not offset sideload/trust and full-trust-helper validation
work for these SMB deployments. NSIS is rejected because it would require a
custom upgrade/security script where MSI already has enterprise deployment and
transaction semantics.

Packaging waits because it does not prove the customer workflow. Freezing,
resource harvesting, signing, MSI authoring, and updater policy begin only after
the live spreadsheet-to-approved-save journey and Windows quality gates pass.
This directly avoids repeating the macOS mistake of building a large packaging
shell before core value exists.

## 9. Development preview and shippable definitions

Phases 1-3 may be demonstrated only as **Birkin for Windows Development
Preview**. The current preview proves transport, protocol negotiation, Python
authority, sole-reader recovery, WPF rendering, and one core Office journey. It
is not a beta, complete, shipped, production-ready, secure-release artifact, or
customer installer.

A Windows build is shippable only when all of these are true:

- The real spreadsheet comparison -> template report -> visible diff -> explicit
  approval -> verified save -> Activity receipt journey passes through the
  installed application and real Python authority.
- Commands, stale cursors, idempotency, restart, gap replay, instance reset,
  capability renewal/expiry, and interrupted outcomes have canonical tests.
- No UI grants approval or enables an unadvertised command; omitted capabilities
  have no placeholder controls.
- Windows 10/11 Korean IME, keyboard-only, Narrator, high contrast, and scaling
  evidence passes on real machines.
- The loopback/discovery trust boundary, redaction, external/owned process
  distinction, and five-in-sixty ceiling pass adversarial tests.
- The self-contained helper/resources and x64 MSI are reproducible, locked,
  Authenticode signed, timestamped, upgradeable, repairable, and uninstallable.
- The installed journey passes without source tree, uv, host Python, or developer
  overrides, and all required Python, Swift, C#, conformance, and CI checks are
  green in one run.

Until then, milestone language must describe the exact proven slice and no more.

## 10. Principal risks and mitigations

| Risk | Mitigation |
| --- | --- |
| C# codec drifts from Python/Swift | One Python-generated artifact, byte parity in both clients, negative code corpus, and live bridge test. |
| Korean composition submits early | Native WPF text control, explicit composition guard, pre-Phase-3 switch gate, and real Windows 10/11 IME evidence. |
| Client becomes a second authority | One-way dependencies, no product persistence, capability-gated controls, canonical replay, and real-authority journeys. |
| Windows process supervision kills an external bridge | Process object from the spawn closure is the only ownership token; PID is diagnostic only. |
| Packaging consumes the project before value exists | Packaging is Phase 5 and cannot start until the Phase 3 office journey and Phase 4 quality gate pass. |
| Terminal or Browser placeholders imply authority | Keep the user-requested regions visibly unavailable/projected-only; only future Python-advertised authority may activate them. |
