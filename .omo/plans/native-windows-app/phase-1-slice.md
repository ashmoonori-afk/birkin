# Phase 1: Windows Development Preview Vertical Slice

Status: executable implementation plan
Exit statement: development preview, not shipped and not customer-ready

## 1. Goal and observable

Phase 1 proves exactly one end-to-end path:

```text
WPF client process
  -> parse BridgeProcess listening announcement
  -> read owner-DACL-protected loopback discovery record
  -> connect to 127.0.0.1
  -> hello / ready / subscribe
  -> receive a real Python workspace snapshot
  -> apply it to an in-memory projection
  -> render its session, cursor, reset reason, and panel count in a real window
```

The bridge is launched with the already-working console-script command:

```powershell
uv run --frozen birkin native-bridge serve --transport loopback --root <temporary-root>
```

The app is visibly titled **Birkin for Windows - Development Preview**. It is
read-only. It has no command submission, terminal panel, product-surface panel,
owned bridge restart, persisted product state, installer, updater, tray icon,
notification, or background launch.

The implementation language is C# with no MVVM, DI, logging, JSON, or socket
framework dependency. Use .NET 8 BCL types, WPF, and MSTest only. The exact
package pins are `Microsoft.NET.Test.Sdk` 17.11.1,
`MSTest.TestFramework` 3.6.4, and `MSTest.TestAdapter` 3.6.4.

## 2. Execution rules

- Execute units in wave order. Units in this thin slice form one critical path;
  they are separated for ownership and review, not forced into unsafe
  concurrency while a shared test project contains RED files.
- Every listed source path has exactly one owner. No unit may edit a path owned
  by another unit.
- In each behavioral unit, create the listed test files first, run the RED
  command, and retain its output in the task execution record. Only then create
  the listed production files.
- RED must fail for the named missing behavior or type. Restore failures,
  unavailable feeds, syntax errors in the test, and unrelated failures are not
  valid RED evidence.
- Tests subscribe to exact events before triggering work and use cancellation
  deadlines. Fixed sleeps and polling are forbidden.
- Unit-specific `--artifacts-path` values keep generated build output isolated.
  Generated `bin`, `obj`, and artifacts are not source write scope and are
  deleted after the wave gate.
- No unit in this file may read or write `birkin/native/serve.py`. The
  platform-aware default being implemented elsewhere is treated as complete;
  every bridge command here still passes `--transport loopback` explicitly.

## 3. Wave table

| Wave | Unit | Dependency | Parallel rule | Exit |
| --- | --- | --- | --- | --- |
| 1 | P1-01 solution scaffold | None | Sole unit because it owns shared project files. | Restore succeeds and all six projects appear in the solution. |
| 2 | P1-02 strict frame/envelope codec | P1-01 | Sole unit because subsequent RED tests depend on its public JSON model. | All 21 Python-generated protocol vectors decode and re-encode identically. |
| 3 | P1-03 announcement, discovery, and handshake | P1-02 | Source scope is disjoint from all later units; execute before P1-04 so each RED is isolated. | A fake loopback server completes the exact handshake and initial subscription. |
| 4 | P1-04 initial projection store | P1-03 | Source scope is disjoint; sequential order preserves isolated RED evidence in Protocol.Tests. | The Python-generated snapshot fixture becomes one validated in-memory state. |
| 5 | P1-05 shell coordinator and presentation | P1-04 | Uses only Protocol public APIs and owns only Shell paths. | Snapshot application publishes one UI-ready immutable presentation. |
| 6 | P1-06 WPF preview and live bridge window | P1-05 | Owns only App and App.Tests paths. | Real bridge handshake and real WPF render pass in one deterministic test. |

No later unit edits an earlier unit's files. If a required API is missing, the
owning earlier unit is resumed; a later unit does not patch across its boundary.

## 4. Unit P1-01 - solution scaffold

### Exclusive write scope

This unit alone may create or edit:

```text
windows/BirkinNativeApp/BirkinNativeApp.sln
windows/BirkinNativeApp/Directory.Build.props
windows/BirkinNativeApp/Directory.Packages.props
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Birkin.Native.Protocol.csproj
windows/BirkinNativeApp/src/Birkin.Native.Shell/Birkin.Native.Shell.csproj
windows/BirkinNativeApp/src/Birkin.Native.App/Birkin.Native.App.csproj
windows/BirkinNativeApp/tests/Birkin.Native.Protocol.Tests/Birkin.Native.Protocol.Tests.csproj
windows/BirkinNativeApp/tests/Birkin.Native.Shell.Tests/Birkin.Native.Shell.Tests.csproj
windows/BirkinNativeApp/tests/Birkin.Native.App.Tests/Birkin.Native.App.Tests.csproj
```

### Failing-first proof

Before creating any listed file, run:

```powershell
dotnet restore .\windows\BirkinNativeApp\BirkinNativeApp.sln
```

Capture RED showing `MSB1009` because the solution does not exist. This is the
repository-shape acceptance check for a nonbehavioral scaffold; a NuGet/network
failure is not acceptable evidence.

### Production change

Create one solution containing three production and three test projects.

- Protocol and Shell target `net8.0`.
- App and App.Tests target `net8.0-windows`, set `UseWPF=true`; App uses
  `OutputType=WinExe`.
- Enable nullable reference types, implicit usings, deterministic builds,
  analyzers, and warnings as errors in `Directory.Build.props`.
- Set `BirkinProductVersion`, `Version`, and `AssemblyInformationalVersion` to
  `0.4.273` in `Directory.Build.props`. That is the independent client version
  required by phase-one ready validation.
- Enable central package management and place only the three exact MSTest pins
  named above in `Directory.Packages.props`.
- Shell references Protocol; App references Shell. Each test project references
  only its same-level production project.
- Protocol.Tests links, with `CopyToOutputDirectory=PreserveNewest`, the exact
  repository files
  `macos/BirkinNativeApp/Tests/BirkinNativeProtocolTests/GoldenVectors/native-protocol-vectors.json`
  and `native-projection-vectors.json`. No Windows fixture copy is created.

An empty WinExe has no generated entry point yet, so the unit gate is restore
and solution membership rather than full build.

### Exact verification command

```powershell
dotnet restore .\windows\BirkinNativeApp\BirkinNativeApp.sln; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; dotnet sln .\windows\BirkinNativeApp\BirkinNativeApp.sln list
```

The list must contain exactly the six project paths above.

## 5. Unit P1-02 - strict frame and envelope codec

### Exclusive write scope

This unit alone may create or edit:

```text
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Framing/NativeProtocolConstants.cs
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Framing/NativeProtocolError.cs
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Framing/NativeJsonValue.cs
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Framing/NativeJsonParser.cs
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Framing/NativeJsonSerializer.cs
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Framing/PythonFloatFormat.cs
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Framing/NativeMessageKind.cs
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Framing/NativeEnvelope.cs
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Framing/NativeBodyValidator.cs
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Framing/NativeFrameCodec.cs
windows/BirkinNativeApp/tests/Birkin.Native.Protocol.Tests/Support/GoldenVectorFixture.cs
windows/BirkinNativeApp/tests/Birkin.Native.Protocol.Tests/Framing/NativeProtocolConstantsTests.cs
windows/BirkinNativeApp/tests/Birkin.Native.Protocol.Tests/Framing/NativeFrameCodecTests.cs
windows/BirkinNativeApp/tests/Birkin.Native.Protocol.Tests/Framing/NativeEnvelopeStrictnessTests.cs
windows/BirkinNativeApp/tests/Birkin.Native.Protocol.Tests/Framing/NativeGoldenVectorParityTests.cs
```

### Failing-first proof

Create all five test files first. Run:

```powershell
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Protocol.Tests\Birkin.Native.Protocol.Tests.csproj -c Debug --artifacts-path .\windows\BirkinNativeApp\artifacts\P1-02 --filter "FullyQualifiedName~NativeProtocolConstantsTests|FullyQualifiedName~NativeFrameCodecTests|FullyQualifiedName~NativeEnvelopeStrictnessTests|FullyQualifiedName~NativeGoldenVectorParityTests"
```

Capture RED with `CS0234`/`CS0246` for the absent Framing types. A test fixture
path error is not valid RED.

### Production change

Implement the version-1 codec exactly as `protocol.md` specifies:

- 4-byte big-endian length plus at most 262,144 UTF-8 JSON bytes;
- ordered JSON value tree parsed with `Utf8JsonReader`;
- duplicate-key, invalid UTF-8, unpaired-surrogate, nonfinite, signed-Int64,
  parser-depth-128, and body-depth-12 enforcement;
- exact six envelope keys, registered kinds, identifier grammar, directions,
  body schemas, and stable error codes;
- deterministic compact serialization and Python-compatible float spelling;
- complete-frame incomplete/trailing/oversize checks.

`NativeProtocolError` carries a stable `Code` and bounded public message.
Tests compare codes and values, not message prose. The golden test decodes all
21 linked Python vectors, compares ordered semantic values and byte counts, and
re-encodes every frame byte-identically.

### Exact verification command

```powershell
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Protocol.Tests\Birkin.Native.Protocol.Tests.csproj -c Debug --artifacts-path .\windows\BirkinNativeApp\artifacts\P1-02 --filter "FullyQualifiedName~NativeProtocolConstantsTests|FullyQualifiedName~NativeFrameCodecTests|FullyQualifiedName~NativeEnvelopeStrictnessTests|FullyQualifiedName~NativeGoldenVectorParityTests"
```

## 6. Unit P1-03 - announcement, discovery, and loopback handshake

### Exclusive write scope

This unit alone may create or edit:

```text
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Messaging/NativeProtocolDate.cs
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Messaging/NativeHandshake.cs
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Transport/BridgeAnnouncement.cs
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Transport/LoopbackDiscoveryRecord.cs
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Transport/DiscoveryRecordReader.cs
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Transport/INativeTransportConnection.cs
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Transport/INativeClientConnection.cs
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Transport/LoopbackTransportConnection.cs
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Transport/NativeClientConnection.cs
windows/BirkinNativeApp/tests/Birkin.Native.Protocol.Tests/Messaging/NativeHandshakeTests.cs
windows/BirkinNativeApp/tests/Birkin.Native.Protocol.Tests/Transport/BridgeAnnouncementTests.cs
windows/BirkinNativeApp/tests/Birkin.Native.Protocol.Tests/Transport/DiscoveryRecordReaderTests.cs
windows/BirkinNativeApp/tests/Birkin.Native.Protocol.Tests/Transport/LoopbackTransportConnectionTests.cs
windows/BirkinNativeApp/tests/Birkin.Native.Protocol.Tests/Transport/NativeClientConnectionTests.cs
windows/BirkinNativeApp/tests/Birkin.Native.Protocol.Tests/Support/LoopbackServerHarness.cs
```

### Failing-first proof

Create the six test/support files first. Run:

```powershell
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Protocol.Tests\Birkin.Native.Protocol.Tests.csproj -c Debug --artifacts-path .\windows\BirkinNativeApp\artifacts\P1-03 --filter "FullyQualifiedName~NativeHandshakeTests|FullyQualifiedName~BridgeAnnouncementTests|FullyQualifiedName~DiscoveryRecordReaderTests|FullyQualifiedName~LoopbackTransportConnectionTests|FullyQualifiedName~NativeClientConnectionTests"
```

Capture RED for missing `BridgeAnnouncement`, `DiscoveryRecordReader`,
`NativeHandshake`, and `NativeClientConnection`. A timeout or occupied port is
not valid RED.

### Production change

Implement one cancellation-aware connection path:

- Strictly parse the exact `listening` stdout object and discovery record.
- Reject unknown/duplicate fields, reparse-point discovery files, non-loopback
  host or transport, invalid/expired secret, unsupported version, invalid port,
  and announcement/record instance or server-version disagreement.
- Connect with `TcpClient` only to `IPAddress.Loopback` and use
  `NetworkStream.ReadExactlyAsync`; never perform DNS resolution.
- Send hello with client `birkin-native-windows`, client version/build
  `0.4.273`, versions `[1]`, surface `windows`, view `window-main`, and the
  one-shot secret.
- Require the correlated ready, exact product-version match, exact body schema,
  protocol 1, and safe limits. Clear the bootstrap secret immediately.
- Send one subscribe for `ready.session_id`, cursor 0, null instance, current
  capability, and an empty surface map.
- Return received validated envelopes through `INativeClientConnection` and
  keep the capability inside the concrete connection object only.
- Track 1,024 frame IDs and enforce connection direction/state/correlation.

`LoopbackServerHarness` uses `TcpListener(IPAddress.Loopback, 0)`, installs its
accept/read signals before client connect, and uses cancellation deadlines. It
must not sleep or poll.

### Exact verification command

```powershell
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Protocol.Tests\Birkin.Native.Protocol.Tests.csproj -c Debug --artifacts-path .\windows\BirkinNativeApp\artifacts\P1-03 --filter "FullyQualifiedName~NativeHandshakeTests|FullyQualifiedName~BridgeAnnouncementTests|FullyQualifiedName~DiscoveryRecordReaderTests|FullyQualifiedName~LoopbackTransportConnectionTests|FullyQualifiedName~NativeClientConnectionTests"
```

## 7. Unit P1-04 - initial projection store

### Exclusive write scope

This unit alone may create or edit:

```text
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Projection/NativeProjectionState.cs
windows/BirkinNativeApp/src/Birkin.Native.Protocol/Projection/NativeProjectionStore.cs
windows/BirkinNativeApp/tests/Birkin.Native.Protocol.Tests/Projection/NativeProjectionSnapshotTests.cs
windows/BirkinNativeApp/tests/Birkin.Native.Protocol.Tests/Projection/NativeProjectionVectorTests.cs
```

### Failing-first proof

Create both test files first. Run:

```powershell
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Protocol.Tests\Birkin.Native.Protocol.Tests.csproj -c Debug --artifacts-path .\windows\BirkinNativeApp\artifacts\P1-04 --filter "FullyQualifiedName~NativeProjectionSnapshotTests|FullyQualifiedName~NativeProjectionVectorTests"
```

Capture RED for missing `NativeProjectionState` and `NativeProjectionStore`.
Failure to locate the already-linked projection fixture is not valid RED.

### Production change

Implement snapshot-only projection application for Phase 1. Require kind
`snapshot` and the exact 12 snapshot body keys. Validate protocol version,
ready session ID, ready instance ID, non-negative cursor, reset reason,
panels, conversation, composer, status, Working Memory, approval policy, and
terminals before replacing state atomically. Retain raw nested product values
as immutable `NativeJsonValue` nodes; do not discard fields simply because the
preview does not display them.

The store has no serializer, file API, preferences dependency, or terminal
lease installation. It exposes immutable state and a `SnapshotApplied` event.
The vector test loads the real Python-generated snapshot and compares every
machine-consumed value to `expected_state`.

Event reduction, gap repair, surface revisions, capability renewal, and
reconnect are Phase 2 work and are not stubbed in Phase 1.

### Exact verification command

```powershell
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Protocol.Tests\Birkin.Native.Protocol.Tests.csproj -c Debug --artifacts-path .\windows\BirkinNativeApp\artifacts\P1-04 --filter "FullyQualifiedName~NativeProjectionSnapshotTests|FullyQualifiedName~NativeProjectionVectorTests"
```

## 8. Unit P1-05 - shell coordinator and presentation

### Exclusive write scope

This unit alone may create or edit:

```text
windows/BirkinNativeApp/src/Birkin.Native.Shell/Connection/ConnectionState.cs
windows/BirkinNativeApp/src/Birkin.Native.Shell/Connection/ConnectionPresentation.cs
windows/BirkinNativeApp/src/Birkin.Native.Shell/Presentation/ShellPresentationModel.cs
windows/BirkinNativeApp/src/Birkin.Native.Shell/Presentation/WorkspaceSnapshotPresentation.cs
windows/BirkinNativeApp/src/Birkin.Native.Shell/ShellCoordinator.cs
windows/BirkinNativeApp/tests/Birkin.Native.Shell.Tests/Connection/ConnectionPresentationTests.cs
windows/BirkinNativeApp/tests/Birkin.Native.Shell.Tests/Presentation/ShellPresentationModelTests.cs
windows/BirkinNativeApp/tests/Birkin.Native.Shell.Tests/ShellCoordinatorTests.cs
```

### Failing-first proof

Create all three tests first. Run:

```powershell
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Shell.Tests\Birkin.Native.Shell.Tests.csproj -c Debug --artifacts-path .\windows\BirkinNativeApp\artifacts\P1-05 --filter "FullyQualifiedName~ConnectionPresentationTests|FullyQualifiedName~ShellPresentationModelTests|FullyQualifiedName~ShellCoordinatorTests"
```

Capture RED for missing `ShellCoordinator` and presentation types. A fake that
returns an unvalidated POCO snapshot is not valid test setup; the coordinator
test must feed a frame through the real Protocol codec and projection store.

### Production change

Implement a WPF-independent coordinator and manually implemented
`INotifyPropertyChanged` presentation model. The state sequence is
Disconnected, Connecting, Handshaking, Subscribing, Ready, or Failed. The
coordinator:

1. subscribes to projection and connection signals;
2. calls `INativeClientConnection` with the parsed announcement and independent
   expected product version;
3. waits for a validated snapshot;
4. applies it to `NativeProjectionStore`;
5. publishes `SnapshotApplied` only after the immutable presentation contains
   session ID, cursor, instance ID, reset reason, transport, and panel count;
6. exposes `LOCAL · PRIVATE` only in Ready and exposes no mutation API.

All model notifications are marshalled through an injected
`SynchronizationContext`; tests provide a deterministic context. Errors become
a bounded failed state without raw exception or record content.

### Exact verification command

```powershell
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Shell.Tests\Birkin.Native.Shell.Tests.csproj -c Debug --artifacts-path .\windows\BirkinNativeApp\artifacts\P1-05 --filter "FullyQualifiedName~ConnectionPresentationTests|FullyQualifiedName~ShellPresentationModelTests|FullyQualifiedName~ShellCoordinatorTests"
```

## 9. Unit P1-06 - WPF development preview and live bridge

### Exclusive write scope

This unit alone may create or edit:

```text
windows/BirkinNativeApp/src/Birkin.Native.App/App.xaml
windows/BirkinNativeApp/src/Birkin.Native.App/App.xaml.cs
windows/BirkinNativeApp/src/Birkin.Native.App/MainWindow.xaml
windows/BirkinNativeApp/src/Birkin.Native.App/MainWindow.xaml.cs
windows/BirkinNativeApp/src/Birkin.Native.App/Startup/AppOptions.cs
windows/BirkinNativeApp/src/Birkin.Native.App/Startup/CompositionRoot.cs
windows/BirkinNativeApp/src/Birkin.Native.App/Startup/DevelopmentPreviewRunner.cs
windows/BirkinNativeApp/src/Birkin.Native.App/Views/WorkspaceSnapshotView.xaml
windows/BirkinNativeApp/src/Birkin.Native.App/Views/WorkspaceSnapshotView.xaml.cs
windows/BirkinNativeApp/tests/Birkin.Native.App.Tests/Startup/AppOptionsTests.cs
windows/BirkinNativeApp/tests/Birkin.Native.App.Tests/Views/WorkspaceSnapshotViewTests.cs
windows/BirkinNativeApp/tests/Birkin.Native.App.Tests/Journeys/LiveBridgeWindowTests.cs
windows/BirkinNativeApp/tests/Birkin.Native.App.Tests/Support/BridgeProcessHarness.cs
windows/BirkinNativeApp/tests/Birkin.Native.App.Tests/Support/StaDispatcherHarness.cs
```

### Failing-first proof

Create the five test/support files first. `BridgeProcessHarness` must already use
`uv` plus discrete `ArgumentList` entries and event-driven stdout capture. Run:

```powershell
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.App.Tests\Birkin.Native.App.Tests.csproj -c Debug --artifacts-path .\windows\BirkinNativeApp\artifacts\P1-06 --filter "FullyQualifiedName~AppOptionsTests|FullyQualifiedName~WorkspaceSnapshotViewTests|FullyQualifiedName~LiveBridgeWindowTests"
```

Capture RED for missing `AppOptions`, `DevelopmentPreviewRunner`, `MainWindow`,
and `WorkspaceSnapshotView`. A bridge startup timeout, malformed test XAML, or
failure to find `uv` is not valid RED.

### Production change

Build one dark, resizable, keyboard-focusable WPF window with a persistent
`DEVELOPMENT PREVIEW` banner. Use native `TextBlock`, `ItemsControl`, and
`ScrollViewer`; do not add WebView2 or a custom text renderer.

`WorkspaceSnapshotView` binds named elements with these automation IDs:

```text
ConnectionStatusText
TransportText
SessionIdText
CursorText
ResetReasonText
PanelCountText
```

It displays only values from `ShellPresentationModel`. The Ready status is
`LOCAL · PRIVATE`; loading and failure remain visibly distinct. The window has
no terminal area and no enabled mutation control.

`AppOptions` accepts exactly
`--bridge-announcement-file <absolute-existing-file>` and rejects missing,
relative, repeated, or unknown arguments. The file must contain one nonblank
JSON line and is a development-only attachment seam. `CompositionRoot` uses
only concrete Protocol/Shell classes and the assembly's independent product
version; no service-container package is added. `App.xaml.cs` shows the window,
then invokes `DevelopmentPreviewRunner` asynchronously and closes the
connection on application exit.

`LiveBridgeWindowTests.ConnectsAndRendersPythonSnapshot` carries both
`[TestCategory("LiveBridge")]` and `[TestCategory("WindowsUI")]`. It:

- starts the real bridge at an empty unique temp root with explicit loopback;
- awaits its stdout announcement, writes that exact line to the options file,
  and passes it through production startup parsing;
- creates and shows `MainWindow` on a dedicated STA dispatcher;
- subscribes to `ContentRendered` and `SnapshotApplied` before connecting;
- awaits both with 30-second cancellation deadlines;
- asserts the window is visible and each named element equals its corresponding
  Python-produced model value; panel count must equal the model count and be
  greater than zero;
- closes on the dispatcher, disposes the client, and asks only the harness-owned
  `Process` object to stop;
- requires empty bridge stderr and deletes all temporary files.

The test must not inject a snapshot, fake a transport, call Python modules in
process, sleep, or poll the visual tree.

### Exact verification command

```powershell
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.App.Tests\Birkin.Native.App.Tests.csproj -c Debug --artifacts-path .\windows\BirkinNativeApp\artifacts\P1-06 --filter "TestCategory=LiveBridge|FullyQualifiedName~AppOptionsTests|FullyQualifiedName~WorkspaceSnapshotViewTests"
```

## 10. Phase exit verification

Run these commands once after all six units are green:

```powershell
uv run --frozen pytest -q tests/test_native_windows_import.py
dotnet restore .\windows\BirkinNativeApp\BirkinNativeApp.sln
dotnet build .\windows\BirkinNativeApp\BirkinNativeApp.sln -c Release --no-restore
dotnet test .\windows\BirkinNativeApp\BirkinNativeApp.sln -c Release --no-build --logger "trx;LogFilePrefix=phase-1-native-windows"
```

The exit evidence must include:

- the parsed `listening` announcement with no bootstrap secret;
- ready protocol/version/instance metadata with capability redacted;
- one Python snapshot's session, cursor, reset reason, and panel count;
- a content-rendered WPF window assertion;
- empty bridge stderr;
- clean process and temporary-directory teardown.

Phase 1 passes only if the live test succeeds in one run. Retries do not turn a
flaky run into evidence.

## 11. Scope and completion audit

The six exclusive scopes above are pairwise disjoint. Shared `.csproj`, solution,
and central property files belong only to P1-01. Protocol framing belongs only
to P1-02; transport only to P1-03; projection only to P1-04; Shell only to
P1-05; WPF App and App.Tests only to P1-06.

No unit touches `birkin/native/serve.py`, `birkin/cli.py`,
`tests/test_native_serve_transport_default.py`, any macOS source, either golden
fixture, or any Python production file. Phase 1 consumes those contracts
read-only.

There are no optional implementations or unresolved choices in this slice.
Passing it proves the path, not product completeness. The artifact must be
called a **development preview**, never "shipped", "complete", "production",
or "customer-ready".
