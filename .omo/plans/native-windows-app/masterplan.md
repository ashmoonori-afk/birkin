# Birkin Native Windows Application Masterplan

Status: implementation decision
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

The first milestone is deliberately one read-only vertical slice: connect to a
live bridge, complete `hello -> ready -> subscribe`, and render one real
Python-produced workspace snapshot in a real WPF window. It is called a
**development preview**, never complete or shipped.

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

There is one switch condition, evaluated before Phase 3 begins. Switch to WinUI
3 only if all of these are true:

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

The client never interprets an external announcement PID as ownership. A
supervisor can stop only a process object returned by its injected spawn
closure. Five owned exits in a rolling 60 seconds enter a stopped state.
Reconnect immediately clears capabilities and terminal leases; instance change
also discards projection and surface state.

Phase 1 has no terminal panel. The first public release also omits Terminal.
Terminal becomes a separately approved post-release capability only after
Python owns a tested ConPTY `CreatePseudoConsole` backend. The client will never
start a local shell itself.

## 6. Phasing and waves

### Phase summary

| Phase | Label | Goal | Exit |
| --- | --- | --- | --- |
| 1 | Development preview | Real bridge, handshake, initial Python snapshot, real WPF window. | One deterministic live-window test passes once. |
| 2 | Resilient read-only foundation | Full protocol hardening, replay/reset, capability lifecycle, supervisor policy, and CI. | Malformed traffic, reconnect, instance reset, and five-in-sixty behavior are green. |
| 3 | Core office workflow alpha | Conversation + jailed files + comparison/report/diff + approval + verified save and receipt. | The named workflow passes through a real bridge and real provider on Windows. |
| 4 | Windows beta quality | Sessions, Working Memory, Activity, desktop navigation, Korean IME, accessibility, and customer-OS evidence. | Windows 10/11 IME, keyboard, Narrator, scaling, and reconnect gates pass. |
| 5 | Signed release candidate | Frozen Python authority, signed x64 MSI, upgrade/uninstall, installed workflow. | Clean-machine signed installed journey passes without repo, uv, or host Python. |

Phase 1 is specified file-by-file in `phase-1-slice.md`. Its six units are
pairwise disjoint, each captures RED before production, and each has an exact
PowerShell command. None touches `birkin/native/serve.py`.

### Phase 2 waves: resilient read-only foundation

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

### Phase 3 waves: core office workflow alpha

| Wave/unit | Exclusive source scope | RED before production | Exact verification |
| --- | --- | --- | --- |
| P3-01 command and receipt wire path | Create `Protocol/Messaging/NativeCommandRequest.cs`; edit `Protocol/Transport/NativeClientConnection.cs`; create `Protocol.Tests/Messaging/{NativeCommandRequestTests,NativeReceiptTests,NativeStaleCursorTests}.cs`. | Add tests first; RED is absent stable-ID/expected-cursor serialization and receipt correlation. | `dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Protocol.Tests\Birkin.Native.Protocol.Tests.csproj -c Debug --filter "FullyQualifiedName~NativeCommandRequestTests|FullyQualifiedName~NativeReceiptTests|FullyQualifiedName~NativeStaleCursorTests"` |
| P3-02 shell office-workflow state | Create `Shell/Commands/{ConversationCommands,ImportCommands,ApprovalCommands,OfficeCommands}.cs` and `Shell/Presentation/{MutationAvailability,OfficeWorkflowPresentation}.cs`; edit `Shell/ShellCoordinator.cs` and `Shell/Presentation/ShellPresentationModel.cs`; create matching files under `Shell.Tests/Commands/` and `Shell.Tests/Presentation/OfficeWorkflowPresentationTests.cs`. | Add tests first; RED requires disabled unadvertised controls, preserved stale-cursor drafts, and no optimistic approval/save success. | `dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Shell.Tests\Birkin.Native.Shell.Tests.csproj -c Debug --filter "TestCategory=OfficeWorkflow"` |
| P3-03 visible workflow and real journey | Create App views `ConversationView`, `ImportView`, `ApprovalView`, `OfficeView`, and `DiffView` (`.xaml` and `.xaml.cs` each); edit `MainWindow.xaml` and `.cs`; create App tests with the same view names, `Journeys/OfficeWorkflowJourneyTests.cs`, and fixtures `Fixtures/Office/{baseline.xlsx,candidate.xlsx,report-template.docx}`. | Add view and journey tests plus binary fixtures first; RED is missing bindings/actions, not provider availability. Then implement the views and wiring. | `dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.App.Tests\Birkin.Native.App.Tests.csproj -c Release --filter "TestCategory=OfficeWorkflow"` |

These units are sequential because each consumes the previous public surface;
their write scopes are still disjoint. The deterministic PR tests use the real
codec and reducer. The phase-exit journey runs on a protected Windows runner
with an existing-account provider and the standard live bridge, not an
alternate test authority:

```powershell
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.App.Tests\Birkin.Native.App.Tests.csproj -c Release --filter "TestCategory=OfficeWorkflow&TestCategory=ExistingAccountProvider"
```

The journey imports two real spreadsheets and an existing document template,
asks Birkin to compare them and draft the report, verifies that the diff is
visible before approval, submits approval through the UI, and validates the
saved output plus Python Activity receipt. Tests compare sentinel cell/document
values, paths, command IDs, cursors, and receipts; they do not pin prompt prose.

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

The hardware gate then executes on Windows 10 22H2 and current Windows 11:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\native\run_windows_client_quality_gate.ps1 -Configuration Release
```

It records app hash, OS build, Microsoft Korean IME profile, display scale,
keyboard/Narrator scenario results, and reconnect result as machine values.
Synthetic CI composition events do not replace this gate.

Browser Aside, Computer Use, voice, and Terminal are not part of the first
public Windows release. Their controls are absent, not placeholders. Office is
included because it is part of the core commercial workflow.

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

The detailed matrix and commands are normative in `test-matrix.md`.

- Python authority and loopback tests run on Ubuntu, macOS, and Windows.
- POSIX UDS/peer-UID tests run on Ubuntu and macOS only.
- Protocol and Shell C# tests run on all three hosted OSes to keep WPF out.
- WPF, live bridge, and MSI tests run on `windows-latest`.
- Swift remains macOS-only.
- Python generates protocol/projection fixtures; Swift and C# consume and
  byte-round-trip them; a live C# journey talks to the real Python bridge.
- The two `WinError 1314` symlink tests are environment-gated only on Windows
  and remain mandatory on Unix. No product fix is proposed for them.
- Async tests await pre-subscribed signals with deadlines. Fixed sleeps and
  polling are forbidden.

## 8. Installer, signing, and update outline

The first public Windows artifact is a WiX Toolset v4 x64 MSI, not MSIX and not
NSIS. WiX is pinned at 4.0.6 and built with `dotnet`, so no Visual Studio IDE is
required. It installs per user under `%LocalAppData%\Programs\Birkin`, requires
Windows 10 22H2 or later, and includes:

- a self-contained `win-x64` WPF publish (no machine .NET dependency);
- a PyInstaller one-folder frozen Python bridge and locked dependencies;
- checksum-pinned runtime resources needed by the core Office/provider journey;
- a signed manifest containing package version, source revision, architecture,
  lock hashes, and every helper/resource hash.

One-folder freezing is chosen over one-file extraction to avoid an extraction
parent, startup races, and antivirus-sensitive temporary executables. The app
launches only the verified serving executable returned by its spawn closure.
The installed workflow does not consult a repository, uv, host Python, browser
cache, or developer bridge override.

The MSI has a stable UpgradeCode, versioned ProductCode, monotonic major-upgrade
rules, downgrade refusal, rollback, repair, and complete uninstall. Updates are
signed full MSI major upgrades delivered through the release HTTPS endpoint,
WinGet, or customer IT tooling. The first public release has no privileged
background updater and no bespoke self-update service.

Signing is inside-out: every shipped `.exe` and `.dll` is Authenticode signed;
`bridge-helper.json` receives a detached CMS signature; the app verifies both
before launch; and the enclosing MSI is Authenticode signed last. Public release
requires a stable publisher identity, an OV/EV code-signing certificate held in
an HSM or Azure Trusted Signing account, credentialed CI, RFC 3161 timestamping,
and a release runner with Windows SDK `signtool` plus .NET `SignedCms`. Unsigned
output is labelled development-only and cannot enter the release channel.

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

Phase 1 may be demonstrated internally only as **Birkin for Windows Development
Preview**. It proves transport, protocol negotiation, Python authority, and WPF
rendering. It is not alpha, complete, shipped, production-ready, secure-release
evidence, or a customer installer.

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
| Terminal parity drives unsafe client shell work | No Terminal in the first release; only a future Python-owned ConPTY capability may add it. |
