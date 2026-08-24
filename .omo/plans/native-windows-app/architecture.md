# Birkin Native Windows Architecture

Status: implementation decision for the Windows development preview
Target framework: .NET 8
UI: WPF on `net8.0-windows`
Local channel: authenticated raw frames over `127.0.0.1`

## 1. Architectural decision

Birkin for Windows is a thin WPF presentation client over the existing Python
native bridge. It adds one implementation language, C#, and XAML for views. It
does not embed Python, host an agent, expose an HTTP service, or define another
wire protocol.

The three projects are deliberately separated as follows:

```text
Birkin.Native.App -> Birkin.Native.Shell -> Birkin.Native.Protocol
                                            |
                                            +-> 127.0.0.1 Python bridge
```

`Birkin.Native.Protocol` and `Birkin.Native.Shell` target plain `net8.0` and
contain no WPF references. Only `Birkin.Native.App` targets
`net8.0-windows` with `UseWPF=true`. This keeps the frame, state, and lifecycle
logic testable without a desktop and makes the split equivalent to the macOS
Protocol / Shell / App split rather than equivalent by filename alone.

Nothing under `birkin/native/`, `birkin/runtime.py`, or the workspace modules may
import or otherwise depend on the Windows tree. Python remains usable without
.NET or the Windows application present.

## 2. Repository and module layout

The committed layout is:

```text
windows/BirkinNativeApp/
  BirkinNativeApp.sln
  Directory.Build.props
  Directory.Packages.props
  src/
    Birkin.Native.Protocol/
      Birkin.Native.Protocol.csproj
      Framing/
        NativeProtocolConstants.cs
        NativeProtocolError.cs
        NativeJsonValue.cs
        NativeJsonParser.cs
        NativeJsonSerializer.cs
        PythonFloatFormat.cs
        NativeMessageKind.cs
        NativeEnvelope.cs
        NativeBodyValidator.cs
        NativeFrameCodec.cs
      Messaging/
        NativeProtocolDate.cs
        NativeHandshake.cs
        NativeCommandRequest.cs
      Projection/
        NativeProjectionState.cs
        NativeProjectionReducer.cs
        NativeProjectionStore.cs
        NativeProjectionSubscription.cs
        NativeReconnect.cs
      Transport/
        BridgeAnnouncement.cs
        LoopbackDiscoveryRecord.cs
        DiscoveryRecordReader.cs
        INativeTransportConnection.cs
        INativeClientConnection.cs
        LoopbackTransportConnection.cs
        NativeClientConnection.cs
    Birkin.Native.Shell/
      Birkin.Native.Shell.csproj
      Connection/
        ConnectionState.cs
        ConnectionPresentation.cs
      Lifecycle/
        IBridgeProcess.cs
        BridgeAttachment.cs
        BridgeSupervisor.cs
      Presentation/
        ShellPresentationModel.cs
        WorkspaceSnapshotPresentation.cs
        MutationAvailability.cs
      Commands/
        ConversationCommands.cs
        ApprovalCommands.cs
        OfficeCommands.cs
        ImportCommands.cs
      ShellCoordinator.cs
    Birkin.Native.App/
      Birkin.Native.App.csproj
      App.xaml
      App.xaml.cs
      MainWindow.xaml
      MainWindow.xaml.cs
      Startup/
        AppOptions.cs
        CompositionRoot.cs
        DevelopmentPreviewRunner.cs
      Views/
        WorkspaceSnapshotView.xaml
        WorkspaceSnapshotView.xaml.cs
        ConversationView.xaml
        ConversationView.xaml.cs
        WorkingMemoryView.xaml
        WorkingMemoryView.xaml.cs
        ApprovalView.xaml
        ApprovalView.xaml.cs
        OfficeView.xaml
        OfficeView.xaml.cs
      Accessibility/
        TextCompositionGuard.cs
  tests/
    Birkin.Native.Protocol.Tests/
      Birkin.Native.Protocol.Tests.csproj
      Framing/
      Messaging/
      Projection/
      Transport/
      Support/
    Birkin.Native.Shell.Tests/
      Birkin.Native.Shell.Tests.csproj
      Connection/
      Lifecycle/
      Presentation/
      Commands/
    Birkin.Native.App.Tests/
      Birkin.Native.App.Tests.csproj
      Startup/
      Views/
      Accessibility/
      Journeys/
      Support/
```

Namespaces follow directories: for example,
`Birkin.Native.Protocol.Framing`, `Birkin.Native.Shell.Lifecycle`, and
`Birkin.Native.App.Views`. Production assemblies do not reference test
assemblies. Test projects may reference only the production project at their
level and its transitive dependencies.

The protocol and shell projects are pure C# ports of behavior, not source-level
ports of Swift. The macOS filenames are a decomposition template: framing,
strict JSON, envelope validation, handshake, projection reduction, reconnect,
and supervisor policies retain the same responsibilities while using .NET
idioms.

## 3. Windows authority boundary

Python is the sole authority for:

- session and conversation state;
- Working Memory, goals, files evidence, and revisions;
- policy, approvals, consent, and command availability;
- agent, tool, Browser, Computer Use, and Office execution;
- terminal creation, leases, process trees, signals, and output;
- audit records, receipts, checkpoints, idempotency, and recovery;
- canonical snapshots, cursor-bearing events, and redacted revisioned product
  surfaces.

The Windows client may:

- render Python-produced snapshots and events;
- keep an in-memory projection cache and transient editing state;
- submit commands with stable command IDs and the expected Python cursor;
- own windowing, focus, keyboard routing, accessibility presentation, and other
  desktop integration;
- persist presentation preferences such as window bounds, theme, font scale,
  and pane layout.

The Windows client must not:

- run another agent, execute tools, or start a client-side shell;
- infer approval, consent, completion, or command success from UI state;
- create a second session database or recover mutations from local guesses;
- persist workspace projections, capabilities, bootstrap secrets, approvals,
  receipts, terminal input, imported product data, or provider credentials;
- enable a command not advertised by `ready.capabilities.commands`;
- turn a notification click, focus change, visible toggle, or process ID into
  authority.

The projection store is a disposable cache. Presentation preferences are stored
under the normal per-user application settings location in a schema that cannot
contain arbitrary product JSON. There is no offline product cache in this
architecture.

## 4. Local channel and trust boundary

Windows always requests the bridge's `loopback` transport. The socket is raw
AF_INET on `127.0.0.1`; it is not HTTP. The client obtains the discovery path
from the bridge's JSON `listening` stdout announcement, then consumes this exact
record shape:

```json
{
  "bootstrap_secret": "<43-char urlsafe base64>",
  "expires_at": "<ISO-8601>",
  "host": "127.0.0.1",
  "instance_id": "<32 lowercase hex>",
  "port": 49152,
  "protocol_versions": [1],
  "server_version": "0.4.273",
  "transport": "loopback"
}
```

The example port is illustrative; production uses the announced ephemeral port.
The reader rejects a non-loopback host, a non-loopback transport, an invalid or
expired record, a version set without 1, an out-of-range port, an instance that
disagrees with the announcement, duplicate JSON keys, unknown keys, and a
reparse-point discovery file. It reads the bootstrap secret once, connects to
the recorded port, sends it only in `hello`, and retains neither the record nor
the secret after `ready`.

Trust enforcement is layered rather than duplicated:

| Layer | Enforcement |
| --- | --- |
| Python bridge | Binds only `127.0.0.1`, creates the private discovery directory and record, applies the protected owner-only DACL, expires and rotates the one-shot secret, mints connection-scoped capabilities, and remains the command/policy authority. |
| Windows ACL and socket stack | Denies other accounts access to the discovery record and prevents a non-loopback destination after the client pins `127.0.0.1`. The executed Windows evidence is owner-only Full Control on both record and directory. |
| C# protocol client | Strictly parses the announcement and record, pins loopback and protocol 1, performs `hello -> ready -> subscribe`, keeps capability material only in memory, enforces frame/body bounds, and refuses version or instance disagreement. |
| WPF shell | Enables mutations only while the connection is ready and the command is advertised; it presents bounded redacted errors and never treats a control as consent. |

Named pipes are rejected. CPython has no named-pipe server, so adopting them
would add a ctypes `CreateNamedPipeW` accept loop without improving the already
proven owner-only boundary. Windows AF_UNIX is also rejected: the existing UDS
implementation and peer-credential checks are POSIX-only, while loopback has
already executed successfully on the target Windows machine. Neither rejected
transport provides a product capability that justifies a second implementation.

## 5. Connection, reconnect, and capability lifecycle

A connection context contains the socket, negotiated protocol version, bridge
instance ID, session ID, current capability and expiries, last contiguous
workspace cursor, and per-surface revisions. It exists only in memory.

Connection state transitions are explicit:

```text
Disconnected -> Connecting -> Handshaking -> Subscribing -> Ready
      ^              |             |              |          |
      +--------------+-------------+--------------+----------+
                     bounded failure or disconnect
```

On any disconnect, before scheduling reconnect, the coordinator atomically:

1. removes the current and predecessor capabilities;
2. removes all terminal lease material and marks any rendered terminal state
   read-only;
3. disables every mutating control;
4. marks the last projection visibly stale, without treating it as current;
5. closes the old socket and creates a new connection context.

The old cursor, known instance ID, and surface revisions may be offered only as
replay hints. `ready.instance_id` controls whether they can be used. A changed
instance discards the entire projection and all revisions before subscribing.
A same-instance contiguous replay advances the cache. A cursor gap,
`stream.desynchronized`, cursor-ahead response, or noncontiguous surface
revision requests canonical repair; the client never fills a gap itself.

`capability.renewed` replaces the in-memory token atomically. The predecessor is
accepted only by Python during its bounded overlap and is not selected for new
client frames. Disconnect, expiry, `goodbye`, or instance reset removes both.
No reconnect automatically resubmits an approval, Office action, import,
configuration change, or terminal mutation. Stable command IDs are reused only
to learn the canonical outcome of the same already-submitted intent.

Reconnect uses bounded exponential delays of 250 ms, 500 ms, 1 s, 2 s, and 5 s
with jitter, then remains at 5 s. Tests inject the scheduler and await state
signals; they do not sleep. A user action can request an immediate reconnect,
but cannot restore stale authority.

## 6. Bridge supervision and application lifecycle

`BridgeSupervisor` distinguishes two states:

- **Attached external:** the announcement came from a user or QA-managed bridge.
  The app owns no process object and never terminates or restarts its PID.
- **Running owned:** the eventual packaged launcher returned an
  `IBridgeProcess` from this supervisor's injected spawn closure. That returned
  process handle, not an announced numeric PID, is the ownership proof.

The supervisor may terminate only the process object returned by its own spawn
closure. It never reopens a process by PID and never kills an externally
announced bridge. On application shutdown it sends `goodbye`, closes the
connection, and asks only an owned process to stop. Python remains responsible
for any terminal process tree.

Unexpected owned exits are tracked with an injected monotonic clock. The fifth
exit in a rolling 60-second window enters a bounded `Stopped(crash_loop)` state;
there is no sixth spawn until an explicit user retry starts a new window. The
same rule applies if a frozen one-file helper has a launcher parent: the spawn
closure must return a wrapper around the serving child it announced, and only
that wrapper may stop it.

Phase 1 uses external attachment through the `listening` stdout line and does
not package or own a bridge. Owned launch, helper verification, graceful
shutdown escalation, and the five-in-sixty restart policy are implemented in
the resilience phase before customer mutation workflows.

## 7. Terminal decision

Phase 1 has no terminal panel, not even a disabled placeholder. Windows lacks
`pty`, `fcntl`, and `termios`, and the bridge correctly reports a typed
unsupported-capability result when no PTY backend exists.

A later terminal panel is permitted only after Python owns a tested ConPTY
(`CreatePseudoConsole`) implementation and advertises the terminal commands.
WPF then renders Python-projected output and sends versioned input, resize,
signal, and close commands carrying the Python lease. The client never starts
`cmd.exe`, PowerShell, or another shell itself. Until that Python capability is
real, omission is the accurate UI.
