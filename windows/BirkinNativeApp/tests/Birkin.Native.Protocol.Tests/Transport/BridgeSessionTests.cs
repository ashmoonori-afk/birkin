using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Tests.Messaging;
using Birkin.Native.Protocol.Tests.Support;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Transport;

[TestClass]
public sealed class BridgeSessionTests
{
    [TestMethod]
    public async Task ConnectAsync_WhenCanonicalEventArrives_UpdatesSharedStoreWithoutManualReceive()
    {
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        var store = new NativeProjectionStore();
        await using var session = new BridgeSession(store);
        var model = new ShellPresentationModel(new ImmediateSynchronizationContext());
        await using var coordinator = new ShellCoordinator(session, store, model);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await ConnectAndSnapshotAsync(server, discovery, session, deadline.Token);
        var rendered = new TaskCompletionSource<WorkspaceSnapshotPresentation>(TaskCreationOptions.RunContinuationsAsynchronously);
        coordinator.SnapshotApplied += snapshot =>
        {
            if (snapshot.Cursor == 1) rendered.TrySetResult(snapshot);
        };

        await server.SendAsync(Event("event-frame-1", 1, "event-1"));
        var projected = await rendered.Task.WaitAsync(deadline.Token);

        Assert.AreSame(store, session.ProjectionStore);
        Assert.AreSame(projected, model.Workspace);
        Assert.AreEqual(1L, projected.Cursor);
        Assert.AreEqual(1L, store.State?.Cursor);
    }

    [TestMethod]
    public async Task ConnectAsync_WhenGoodbyeArrivesBeforeInitialSnapshot_FaultsWithoutHanging()
    {
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var session = new BridgeSession(new NativeProjectionStore());
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var connecting = session.ConnectAsync(discovery.Announcement, TestDiscovery.Version, deadline.Token);
        var hello = await server.ReceiveAsync();
        await server.SendAsync(Ready(hello.Id));
        _ = await server.ReceiveAsync();

        await server.SendAsync(Goodbye("shutdown-before-snapshot"));

        await Assert.ThrowsExceptionAsync<IOException>(() => connecting.WaitAsync(deadline.Token));
        Assert.AreEqual(0, ActiveReceiveCount(session));
    }

    [TestMethod]
    public async Task ConnectAsync_WhenErrorArrivesBeforeInitialSnapshot_FaultsWithoutHanging()
    {
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var session = new BridgeSession(new NativeProjectionStore());
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var connecting = session.ConnectAsync(discovery.Announcement, TestDiscovery.Version, deadline.Token);
        var hello = await server.ReceiveAsync();
        await server.SendAsync(Ready(hello.Id));
        _ = await server.ReceiveAsync();

        await server.SendAsync(new NativeEnvelope(
            NativeMessageKind.Error,
            "error-before-snapshot",
            Object(
                ("code", new NativeJsonString("E_STATE")),
                ("message", new NativeJsonString("subscription ended")),
                ("retryable", new NativeJsonBoolean(false)))));

        await Assert.ThrowsExceptionAsync<IOException>(() => connecting.WaitAsync(deadline.Token));
        Assert.AreEqual(0, ActiveReceiveCount(session));
    }

    [TestMethod]
    public async Task ConnectAsync_WhenSessionLifetimeIsCancelledBeforeSnapshot_StopsWithoutHanging()
    {
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var session = new BridgeSession(new NativeProjectionStore());
        using var cancellation = new CancellationTokenSource();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var connecting = session.ConnectAsync(discovery.Announcement, TestDiscovery.Version, cancellation.Token);
        var hello = await server.ReceiveAsync();
        await server.SendAsync(Ready(hello.Id));
        _ = await server.ReceiveAsync();

        cancellation.Cancel();

        await Assert.ThrowsExceptionAsync<OperationCanceledException>(() => connecting.WaitAsync(deadline.Token));
        Assert.AreEqual(0, ActiveReceiveCount(session));
    }

    [TestMethod]
    public async Task ConnectedSession_WhenIdlePingArrives_EmitsAuthenticatedPongWithoutCommandOrManualReceive()
    {
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var session = new BridgeSession(new NativeProjectionStore());
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await ConnectAndSnapshotAsync(server, discovery, session, deadline.Token);
        const string sentAt = "2026-08-24T02:45:00+00:00";
        var ping = new NativeEnvelope(NativeMessageKind.Ping, "idle-ping", Object(
            ("sent_at", new NativeJsonString(sentAt))));

        await server.SendAsync(ping);
        var pong = await server.ReceiveAsync();

        Assert.AreEqual(NativeMessageKind.Pong, pong.Kind);
        Assert.AreEqual(ping.Id, pong.InReplyTo);
        Assert.AreEqual(sentAt, String(pong.Body, "sent_at"));
    }

    [TestMethod]
    public async Task SendCommandForResultAsync_WhenEventPrecedesReceipt_CorrelatesBothWithSoleReader()
    {
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        var store = new NativeProjectionStore();
        await using var session = new BridgeSession(store);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await ConnectAndSnapshotAsync(server, discovery, session, deadline.Token);
        var projected = new TaskCompletionSource<NativeProjectionState>(TaskCreationOptions.RunContinuationsAsynchronously);
        store.CanonicalApplied += _ =>
        {
            if (store.State is { Cursor: 1 } state) projected.TrySetResult(state);
        };
        var commandResult = session.SendCommandForResultAsync(Request("command-1"), deadline.Token).AsTask();
        var command = await server.ReceiveAsync();

        await server.SendAsync(Event("event-before-receipt", 1, "command-1"));
        await projected.Task.WaitAsync(deadline.Token);
        await server.SendAsync(Receipt("receipt-1", command.Id, "command-1"));
        var receipt = await commandResult.WaitAsync(deadline.Token);

        Assert.AreEqual(NativeMessageKind.Receipt, receipt.Kind);
        Assert.AreEqual(command.Id, receipt.InReplyTo);
        Assert.AreEqual(1L, store.State?.Cursor);
        Assert.AreEqual(1, session.MaximumConcurrentReceives);
    }

    [TestMethod]
    public async Task CursorGap_RequestsExactlyOneCanonicalReplayAndRemainsDisabledUntilSnapshot()
    {
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        var store = new NativeProjectionStore();
        await using var session = new BridgeSession(store);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await ConnectAndSnapshotAsync(server, discovery, session, deadline.Token);
        var replayStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        store.RecoveryStateChanged += state =>
        {
            if (state == NativeProjectionRecoveryState.ReplayInFlight) replayStarted.TrySetResult();
        };

        await server.SendAsync(Event("gap-1", 2, "command-gap"));
        await replayStarted.Task.WaitAsync(deadline.Token);
        var replay = await server.ReceiveAsync();
        await server.SendAsync(Event("gap-2", 3, "command-gap"));

        Assert.AreEqual(NativeMessageKind.Subscribe, replay.Kind);
        Assert.AreEqual(1, session.CanonicalRepairRequestCount);
        Assert.AreEqual(NativeProjectionRecoveryState.ReplayInFlight, store.RecoveryState);
        Assert.IsFalse(store.IsMutationAuthorityAvailable);

        var live = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        store.RecoveryStateChanged += state =>
        {
            if (state == NativeProjectionRecoveryState.Live) live.TrySetResult();
        };
        await server.SendAsync(Snapshot("replacement-snapshot"));
        await live.Task.WaitAsync(deadline.Token);

        Assert.AreEqual(NativeProjectionRecoveryState.Live, store.RecoveryState);
        Assert.IsTrue(store.IsMutationAuthorityAvailable);
    }

    [TestMethod]
    public async Task SurfaceGapAndDesynchronized_UseOneRepairEpisodeGate()
    {
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        var store = new NativeProjectionStore();
        await using var session = new BridgeSession(store);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await ConnectAndSnapshotAsync(server, discovery, session, deadline.Token);
        var surfaceApplied = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        store.CanonicalApplied += envelope =>
        {
            if (envelope.Kind == NativeMessageKind.SurfaceSnapshot) surfaceApplied.TrySetResult();
        };
        await server.SendAsync(Surface(NativeMessageKind.SurfaceSnapshot, 1));
        await surfaceApplied.Task.WaitAsync(deadline.Token);
        var replayStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        store.RecoveryStateChanged += state =>
        {
            if (state == NativeProjectionRecoveryState.ReplayInFlight) replayStarted.TrySetResult();
        };

        await server.SendAsync(Surface(NativeMessageKind.SurfaceEvent, 3));
        await replayStarted.Task.WaitAsync(deadline.Token);
        _ = await server.ReceiveAsync();
        await server.SendAsync(new NativeEnvelope(
            NativeMessageKind.StreamDesynchronized,
            "desync-same-episode",
            Object(("resume_after", new NativeJsonInteger(0)))));
        var replaced = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        store.SnapshotApplied += _ => replaced.TrySetResult();
        await server.SendAsync(Snapshot("surface-replacement"));
        await replaced.Task.WaitAsync(deadline.Token);

        Assert.AreEqual(1, session.CanonicalRepairRequestCount);
        Assert.AreEqual(NativeProjectionRecoveryState.Live, store.RecoveryState);
    }

    [TestMethod]
    public async Task ReportHeartbeatMiss_WhenCommandPending_ImmediatelyFaultsAndDisablesMutations()
    {
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        var store = new NativeProjectionStore();
        await using var session = new BridgeSession(store);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await ConnectAndSnapshotAsync(server, discovery, session, deadline.Token);
        var pending = session.SendCommandForResultAsync(Request("heartbeat-pending"), deadline.Token).AsTask();
        _ = await server.ReceiveAsync();

        session.ReportHeartbeatMiss();

        await Assert.ThrowsExceptionAsync<IOException>(() => pending.WaitAsync(deadline.Token));
        Assert.IsFalse(store.IsMutationAuthorityAvailable);
        Assert.AreEqual(NativeProjectionRecoveryState.GapDetected, store.RecoveryState);
    }

    [TestMethod]
    public async Task HeartbeatRepair_WhenFaultedCommandReceiptArrivesLate_ContinuesReceiveLoop()
    {
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        var store = new NativeProjectionStore();
        await using var session = new BridgeSession(store);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await ConnectAndSnapshotAsync(server, discovery, session, deadline.Token);
        var pending = session.SendCommandForResultAsync(Request("heartbeat-late"), deadline.Token).AsTask();
        var command = await server.ReceiveAsync();

        await session.ReportHeartbeatMissAsync(deadline.Token);
        _ = await server.ReceiveAsync();
        await Assert.ThrowsExceptionAsync<IOException>(() => pending.WaitAsync(deadline.Token));
        await server.SendAsync(Receipt("late-receipt", command.Id, "heartbeat-late"));
        var replaced = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        store.SnapshotApplied += _ => replaced.TrySetResult();
        await server.SendAsync(Snapshot("heartbeat-replacement"));
        await replaced.Task.WaitAsync(deadline.Token);
        var projected = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        store.CanonicalApplied += envelope =>
        {
            if (envelope.Kind == NativeMessageKind.Event) projected.TrySetResult();
        };
        await server.SendAsync(Event("after-late-receipt", 1, "later-command"));
        await projected.Task.WaitAsync(deadline.Token);

        Assert.AreEqual(1L, store.State?.Cursor);
        Assert.AreEqual(1, session.MaximumConcurrentReceives);
    }

    [TestMethod]
    public async Task SendCommandForResultAsync_WhenCommandTokenCancels_ClearsOnlyThatCommand()
    {
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var session = new BridgeSession(new NativeProjectionStore());
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await ConnectAndSnapshotAsync(server, discovery, session, deadline.Token);
        using var commandCancellation = new CancellationTokenSource();
        var firstResult = session.SendCommandForResultAsync(
            Request("cancelled-command"), commandCancellation.Token).AsTask();
        var firstCommand = await server.ReceiveAsync();

        commandCancellation.Cancel();
        await Assert.ThrowsExceptionAsync<TaskCanceledException>(() => firstResult.WaitAsync(deadline.Token));
        await server.SendAsync(Receipt("cancelled-late-receipt", firstCommand.Id, "cancelled-command"));
        var secondResult = session.SendCommandForResultAsync(Request("next-command"), deadline.Token).AsTask();
        var secondCommand = await server.ReceiveAsync();
        await server.SendAsync(Receipt("next-receipt", secondCommand.Id, "next-command"));
        var receipt = await secondResult.WaitAsync(deadline.Token);

        Assert.AreEqual("next-command", String(receipt.Body, "command_id"));
        Assert.AreEqual(1, session.MaximumConcurrentReceives);
    }

    [TestMethod]
    public async Task SendGoodbyeAsync_WhenConnected_WritesAuthenticatedOrderlyFrame()
    {
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var session = new BridgeSession(new NativeProjectionStore());
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await ConnectAndSnapshotAsync(server, discovery, session, deadline.Token);

        await session.SendGoodbyeAsync(deadline.Token);
        var goodbye = await server.ReceiveAsync();

        Assert.AreEqual(NativeMessageKind.Goodbye, goodbye.Kind);
        Assert.AreEqual("app_shutdown", String(goodbye.Body, "reason"));
        Assert.AreEqual("capability-token", String(goodbye.Body, "session_capability"));
    }

    [TestMethod]
    public async Task ReconnectAsync_WhenEndpointIsReplaced_UsesSameSessionWithoutSecondReader()
    {
        await using var firstServer = new LoopbackServerHarness();
        await using var secondServer = new LoopbackServerHarness();
        using var firstDiscovery = TestDiscovery.Create(firstServer.Port);
        using var secondDiscovery = TestDiscovery.Create(secondServer.Port);
        await using var session = new BridgeSession(new NativeProjectionStore());
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await ConnectAndSnapshotAsync(firstServer, firstDiscovery, session, deadline.Token);

        var reconnecting = session.ReconnectAsync(
            secondDiscovery.Announcement,
            TestDiscovery.Version,
            deadline.Token);
        var hello = await secondServer.ReceiveAsync();
        await secondServer.SendAsync(Ready(hello.Id));
        _ = await secondServer.ReceiveAsync();
        await secondServer.SendAsync(Snapshot("replacement-endpoint-snapshot"));
        await reconnecting;

        Assert.AreEqual(1, session.MaximumConcurrentReceives);
        Assert.AreEqual(NativeProjectionRecoveryState.Live, session.ProjectionStore.RecoveryState);
    }

    [TestMethod]
    public async Task ReconnectAsync_WhenDisposeRacesAfterLifecycleGateEntry_CancellationIsNotMasked()
    {
        await using var firstServer = new LoopbackServerHarness();
        await using var secondServer = new LoopbackServerHarness();
        using var firstDiscovery = TestDiscovery.Create(firstServer.Port);
        using var secondDiscovery = TestDiscovery.Create(secondServer.Port);
        var session = new BridgeSession(new NativeProjectionStore());
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await ConnectAndSnapshotAsync(firstServer, firstDiscovery, session, deadline.Token);

        var reconnecting = session.ReconnectAsync(
            secondDiscovery.Announcement,
            TestDiscovery.Version,
            deadline.Token);
        _ = await secondServer.ReceiveAsync();

        var disposing = session.DisposeAsync().AsTask();
        var reconnectError = await CaptureExceptionAsync(reconnecting).WaitAsync(deadline.Token);
        await disposing.WaitAsync(deadline.Token);

        Assert.IsInstanceOfType<OperationCanceledException>(reconnectError);
        Assert.IsNotInstanceOfType<ObjectDisposedException>(reconnectError);
        Assert.AreEqual(0, ActiveReceiveCount(session));
        Assert.AreEqual(1, session.MaximumConcurrentReceives);
    }

    [TestMethod]
    public async Task ReconnectAsync_WhenDisposeCompletesFirst_ThrowsSessionDisposedBeforeConnecting()
    {
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        var session = new BridgeSession(new NativeProjectionStore());
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));

        await session.DisposeAsync();
        var error = await Assert.ThrowsExceptionAsync<ObjectDisposedException>(() => session.ReconnectAsync(
            discovery.Announcement,
            TestDiscovery.Version,
            deadline.Token));

        Assert.AreEqual(typeof(BridgeSession).FullName, error.ObjectName);
        Assert.IsFalse(server.HasAcceptedClient);
        Assert.AreEqual(0, ActiveReceiveCount(session));
    }

    [TestMethod]
    public async Task DisposeAsync_WhenReconnectCompletesFirst_FaultsPendingOnceAndCleansSoleReader()
    {
        await using var firstServer = new LoopbackServerHarness();
        await using var secondServer = new LoopbackServerHarness();
        using var firstDiscovery = TestDiscovery.Create(firstServer.Port);
        using var secondDiscovery = TestDiscovery.Create(secondServer.Port);
        var store = new NativeProjectionStore();
        var session = new BridgeSession(store);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await ConnectAndSnapshotAsync(firstServer, firstDiscovery, session, deadline.Token);
        var authorityRevoked = 0;
        store.RecoveryStateChanged += state =>
        {
            if (state == NativeProjectionRecoveryState.Disconnected)
            {
                authorityRevoked++;
            }
        };

        var reconnecting = session.ReconnectAsync(
            secondDiscovery.Announcement,
            TestDiscovery.Version,
            deadline.Token);
        var hello = await secondServer.ReceiveAsync();
        await secondServer.SendAsync(Ready(hello.Id));
        _ = await secondServer.ReceiveAsync();
        await secondServer.SendAsync(Snapshot("dispose-after-reconnect-snapshot"));
        await reconnecting;
        authorityRevoked = 0;
        var pending = session.SendCommandForResultAsync(Request("dispose-pending"), deadline.Token).AsTask();
        _ = await secondServer.ReceiveAsync();

        await session.DisposeAsync();
        var firstError = await CaptureExceptionAsync(pending).WaitAsync(deadline.Token);
        var secondError = await CaptureExceptionAsync(pending).WaitAsync(deadline.Token);

        Assert.AreSame(firstError, secondError);
        Assert.IsInstanceOfType<OperationCanceledException>(firstError);
        Assert.AreEqual(1, authorityRevoked);
        Assert.AreEqual(0, ActiveReceiveCount(session));
        Assert.AreEqual(1, session.MaximumConcurrentReceives);
        Assert.IsFalse(store.IsMutationAuthorityAvailable);
    }

    [TestMethod]
    public async Task DisposeAsync_WhenCalledConcurrently_IsIdempotent()
    {
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        var store = new NativeProjectionStore();
        var session = new BridgeSession(store);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await ConnectAndSnapshotAsync(server, discovery, session, deadline.Token);
        var authorityRevoked = 0;
        store.RecoveryStateChanged += state =>
        {
            if (state == NativeProjectionRecoveryState.Disconnected)
            {
                authorityRevoked++;
            }
        };

        var first = session.DisposeAsync().AsTask();
        var second = session.DisposeAsync().AsTask();
        await Task.WhenAll(first, second).WaitAsync(deadline.Token);

        Assert.AreEqual(1, authorityRevoked);
        Assert.AreEqual(0, ActiveReceiveCount(session));
        Assert.AreEqual(1, session.MaximumConcurrentReceives);
    }

    [TestMethod]
    public async Task Disconnect_WhenCommandPending_FaultsCommandAndRevokesMutationAuthority()
    {
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        var store = new NativeProjectionStore();
        await using var session = new BridgeSession(store);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await ConnectAndSnapshotAsync(server, discovery, session, deadline.Token);
        var commandResult = session.SendCommandForResultAsync(Request("pending-command"), deadline.Token).AsTask();
        _ = await server.ReceiveAsync();

        await server.DisconnectClientAsync();
        await Assert.ThrowsExceptionAsync<IOException>(() => commandResult.WaitAsync(deadline.Token));

        Assert.IsFalse(session.HasLiveCapability(DateTimeOffset.UtcNow));
        Assert.IsFalse(store.IsMutationAuthorityAvailable);
        await Assert.ThrowsExceptionAsync<NativeProtocolError>(
            () => session.SendCommandForResultAsync(Request("after-shutdown"), deadline.Token).AsTask());
    }

    private static async Task ConnectAndSnapshotAsync(
        LoopbackServerHarness server,
        TestDiscovery discovery,
        BridgeSession session,
        CancellationToken cancellationToken)
    {
        var connecting = session.ConnectAsync(discovery.Announcement, TestDiscovery.Version, cancellationToken);
        var hello = await server.ReceiveAsync();
        await server.SendAsync(Ready(hello.Id));
        _ = await server.ReceiveAsync();
        await server.SendAsync(Snapshot());
        await connecting;
    }

    private static int ActiveReceiveCount(BridgeSession session)
    {
        var field = typeof(BridgeSession).GetField(
            "_activeReceives",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("BridgeSession active receive counter is unavailable.");
        return (int)(field.GetValue(session)
            ?? throw new InvalidOperationException("BridgeSession active receive counter is null."));
    }

    private static async Task<Exception> CaptureExceptionAsync(Task task)
    {
        try
        {
            await task;
        }
        catch (Exception error)
        {
            return error;
        }

        Assert.Fail("Expected the task to fault.");
        throw new InvalidOperationException("Assert.Fail unexpectedly returned.");
    }

    private static NativeEnvelope Ready(string reply)
    {
        var ready = NativeHandshakeTests.Ready(reply);
        return new NativeEnvelope(
            ready.Kind,
            new NativeEnvelopeIdentity(ready.Id, ready.InReplyTo),
            new NativeJsonObject(ready.Body.Pairs.Select(pair => pair.Key == "capability"
                ? new KeyValuePair<string, NativeJsonValue>(pair.Key, Object(
                    ("token", new NativeJsonString("capability-token")),
                    ("expires_at", new NativeJsonString("2099-08-24T02:00:00+00:00")),
                    ("hard_expires_at", new NativeJsonString("2099-08-24T08:00:00+00:00"))))
                : pair)));
    }

    private static NativeCommandRequest Request(string commandId) => new(
        new NativeCommandIdentity(commandId, 0),
        new NativeCommandIntent("chat.send", Object(("text", new NativeJsonString("hello")))),
        "conversation");

    private static NativeEnvelope Snapshot(string id = "snapshot-1") => new(
        NativeMessageKind.Snapshot,
        id,
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("session_id", new NativeJsonString("native-app")),
            ("cursor", new NativeJsonInteger(0)),
            ("panels", new NativeJsonArray([])),
            ("conversation", new NativeJsonArray([])),
            ("composer", Object(("can_send", new NativeJsonBoolean(true)))),
            ("status", Object()),
            ("working_memory", Object()),
            ("approval_policy", Object()),
            ("terminals", new NativeJsonArray([])),
            ("instance_id", new NativeJsonString(TestDiscovery.InstanceId)),
            ("reset_reason", new NativeJsonString("initial"))));

    private static NativeEnvelope Event(string id, long cursor, string commandId) => new(
        NativeMessageKind.Event,
        id,
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("event_id", new NativeJsonString(id)),
            ("session_id", new NativeJsonString("native-app")),
            ("actor_id", new NativeJsonString("windows:test")),
            ("cursor", new NativeJsonInteger(cursor)),
            ("type", new NativeJsonString("command.completed")),
            ("timestamp", new NativeJsonString("2026-08-24T01:00:00+00:00")),
            ("command_id", new NativeJsonString(commandId)),
            ("payload", Object(("outcome", new NativeJsonString("accepted"))))));

    private static NativeEnvelope Surface(NativeMessageKind kind, long revision) => new(
        kind,
        $"surface-{revision}",
        Object(
            ("surface", new NativeJsonString("browser_aside")),
            ("revision", new NativeJsonInteger(revision)),
            ("payload", Object())));

    private static NativeEnvelope Goodbye(string reason) => new(
        NativeMessageKind.Goodbye,
        "server-goodbye",
        Object(("reason", new NativeJsonString(reason))));

    private static NativeEnvelope Receipt(string id, string reply, string commandId) => new(
        NativeMessageKind.Receipt,
        new NativeEnvelopeIdentity(id, reply),
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("command_id", new NativeJsonString(commandId)),
            ("session_id", new NativeJsonString("native-app")),
            ("actor_id", new NativeJsonString("windows:test")),
            ("accepted_cursor", new NativeJsonInteger(1)),
            ("state", new NativeJsonString("completed")),
            ("result_event_cursor", new NativeJsonInteger(1)),
            ("duplicate", new NativeJsonBoolean(false)),
            ("outcome", new NativeJsonString("accepted"))));

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));

    private static string String(NativeJsonObject body, string key) =>
        ((NativeJsonString)body[key]!).Value;

    private sealed class ImmediateSynchronizationContext : SynchronizationContext
    {
        public override void Post(SendOrPostCallback callback, object? state) => callback(state);
    }
}
