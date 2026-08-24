using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;
using Birkin.Native.Shell.Tests.Support;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests;

[TestClass]
public sealed class ShellCoordinatorStreamTests
{
    private const string ExpectedProductVersion = "independent-client-version";
    private const string InstanceId = "0123456789abcdef0123456789abcdef";

    [TestMethod]
    public async Task ConnectAsync_WhenControlFramesPrecedeSnapshot_WaitsForAuthoritativeSnapshot()
    {
        // Given
        var connection = new ScriptedNativeClientConnection();
        connection.Enqueue(PingEnvelope());
        connection.Enqueue(CapabilityRenewalEnvelope());
        connection.Enqueue(SnapshotEnvelope());
        var model = new ShellPresentationModel(new ImmediateSynchronizationContext());
        await using var coordinator = new ShellCoordinator(connection, new NativeProjectionStore(), model);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));

        // When
        await coordinator.ConnectAsync(AnnouncementJson(), ExpectedProductVersion, deadline.Token);

        // Then
        Assert.AreEqual(ConnectionState.Ready, model.Connection.State);
        Assert.AreEqual(42L, model.Workspace?.Cursor);
        Assert.AreEqual(1, connection.MaxConcurrentReceives);
    }

    [TestMethod]
    public async Task ConnectAsync_WhenLiveFramesFollowInitialSnapshot_AppliesEveryProjectionInOrder()
    {
        // Given
        var connection = new ScriptedNativeClientConnection();
        connection.Enqueue(SnapshotEnvelope());
        var store = new NativeProjectionStore();
        var model = new ShellPresentationModel(new ImmediateSynchronizationContext());
        await using var coordinator = new ShellCoordinator(connection, store, model);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await coordinator.ConnectAsync(AnnouncementJson(), ExpectedProductVersion, deadline.Token);
        var updated = WorkspaceAtCursor(model, 44);

        // When
        connection.Enqueue(PingEnvelope());
        connection.Enqueue(CapabilityRenewalEnvelope());
        connection.Enqueue(EventEnvelope(43, "message.user", "first live frame"));
        connection.Enqueue(SurfaceEnvelope());
        connection.Enqueue(EventEnvelope(44, "message.assistant.completed", "post-snapshot update"));
        await updated.Task.WaitAsync(deadline.Token);

        // Then
        Assert.AreEqual(44L, store.State?.Cursor);
        Assert.AreEqual(44L, model.Workspace?.Cursor);
        Assert.AreEqual(1L, store.Surface("browser_aside")?.Revision);
        Assert.AreEqual(1, connection.MaxConcurrentReceives);
    }

    [TestMethod]
    public async Task ConnectAsync_WhenConnectionReconnects_ContinuesTheSameOwnedReceive()
    {
        // Given
        var connection = new ScriptedNativeClientConnection();
        connection.Enqueue(SnapshotEnvelope());
        var store = new NativeProjectionStore();
        var model = new ShellPresentationModel(new ImmediateSynchronizationContext());
        await using var coordinator = new ShellCoordinator(connection, store, model);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await coordinator.ConnectAsync(AnnouncementJson(), ExpectedProductVersion, deadline.Token);
        var updated = WorkspaceAtCursor(model, 43);

        // When
        connection.EnqueueReconnect();
        connection.Enqueue(EventEnvelope(43, "message.user", "replayed after reconnect"));
        await connection.Reconnected.Task.WaitAsync(deadline.Token);
        await updated.Task.WaitAsync(deadline.Token);

        // Then
        Assert.AreEqual(43L, store.State?.Cursor);
        Assert.AreEqual(1, connection.Reconnects);
        Assert.AreEqual(1, connection.MaxConcurrentReceives);
    }

    [TestMethod]
    public async Task ConnectAsync_WhenLiveReceiveIsCancelled_StopsPumpAndPublishesBoundedFailure()
    {
        // Given
        var connection = new ScriptedNativeClientConnection();
        connection.Enqueue(SnapshotEnvelope());
        var model = new ShellPresentationModel(new ImmediateSynchronizationContext());
        var coordinator = new ShellCoordinator(connection, new NativeProjectionStore(), model);
        using var cancellation = new CancellationTokenSource();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await coordinator.ConnectAsync(AnnouncementJson(), ExpectedProductVersion, cancellation.Token);
        var failed = ConnectionStateReached(coordinator, ConnectionState.Failed);

        // When
        cancellation.Cancel();
        await connection.ReceiveCancelled.Task.WaitAsync(deadline.Token);
        await failed.Task.WaitAsync(deadline.Token);
        await coordinator.DisposeAsync();

        // Then
        Assert.AreEqual(ConnectionState.Failed, model.Connection.State);
        Assert.AreEqual("E_CANCELLED", model.Connection.ErrorCode);
        Assert.AreEqual(0, connection.ActiveReceives);
        Assert.AreEqual(1, connection.DisposeCalls);
    }

    [TestMethod]
    public async Task ConnectAsync_WhenLiveFrameIsMalformed_StopsPumpAndPublishesProtocolFailure()
    {
        // Given
        var connection = new ScriptedNativeClientConnection();
        connection.Enqueue(SnapshotEnvelope());
        var store = new NativeProjectionStore();
        var model = new ShellPresentationModel(new ImmediateSynchronizationContext());
        await using var coordinator = new ShellCoordinator(connection, store, model);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await coordinator.ConnectAsync(AnnouncementJson(), ExpectedProductVersion, deadline.Token);
        var failed = ConnectionStateReached(coordinator, ConnectionState.Failed);

        // When
        connection.Enqueue(new NativeEnvelope(NativeMessageKind.Event, "malformed-event", Object()));
        await failed.Task.WaitAsync(deadline.Token);

        // Then
        Assert.AreEqual("E_BODY", model.Connection.ErrorCode);
        Assert.AreEqual(42L, store.State?.Cursor);
        Assert.AreEqual(0, connection.ActiveReceives);
        Assert.AreEqual(1, connection.MaxConcurrentReceives);
    }

    private static TaskCompletionSource WorkspaceAtCursor(ShellPresentationModel model, long cursor)
    {
        var reached = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        model.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(ShellPresentationModel.Workspace)
                && model.Workspace?.Cursor == cursor)
            {
                reached.TrySetResult();
            }
        };
        return reached;
    }

    private static TaskCompletionSource ConnectionStateReached(ShellCoordinator coordinator, ConnectionState state)
    {
        var reached = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        coordinator.ConnectionStateChanged += current =>
        {
            if (current == state)
            {
                reached.TrySetResult();
            }
        };
        return reached;
    }

    private static NativeEnvelope SnapshotEnvelope() => new(
        NativeMessageKind.Snapshot,
        "server-snapshot-1",
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("session_id", new NativeJsonString("session-1")),
            ("cursor", new NativeJsonInteger(42)),
            ("panels", new NativeJsonArray([])),
            ("conversation", new NativeJsonArray([])),
            ("composer", Object()),
            ("status", Object()),
            ("working_memory", Object()),
            ("approval_policy", Object()),
            ("terminals", new NativeJsonArray([])),
            ("instance_id", new NativeJsonString(InstanceId)),
            ("reset_reason", new NativeJsonString("initial"))));

    private static NativeEnvelope EventEnvelope(long cursor, string type, string text) => new(
        NativeMessageKind.Event,
        $"server-event-{cursor}",
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("session_id", new NativeJsonString("session-1")),
            ("cursor", new NativeJsonInteger(cursor)),
            ("event_id", new NativeJsonString($"event-{cursor}")),
            ("type", new NativeJsonString(type)),
            ("timestamp", new NativeJsonString("2026-08-24T02:45:00+00:00")),
            ("actor_id", new NativeJsonString("test:stream")),
            ("command_id", new NativeJsonString("command-1")),
            ("payload", Object(("text", new NativeJsonString(text))))));

    private static NativeEnvelope SurfaceEnvelope() => new(
        NativeMessageKind.SurfaceSnapshot,
        "surface-1",
        Object(
            ("surface", new NativeJsonString("browser_aside")),
            ("revision", new NativeJsonInteger(1)),
            ("payload", Object(("title", new NativeJsonString("live"))))));

    private static NativeEnvelope PingEnvelope() => new(
        NativeMessageKind.Ping,
        "ping-1",
        Object(("sent_at", new NativeJsonString("2026-08-24T02:45:00+00:00"))));

    private static NativeEnvelope CapabilityRenewalEnvelope() => new(
        NativeMessageKind.CapabilityRenewed,
        "renewal-1",
        Object(
            ("token", new NativeJsonString("renewed-capability")),
            ("expires_at", new NativeJsonString("2026-08-24T03:00:00+00:00")),
            ("hard_expires_at", new NativeJsonString("2026-08-24T08:00:00+00:00"))));

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));

    private static string AnnouncementJson() =>
        $$"""{"event":"listening","transport":"loopback","pid":1904,"root":"C:\\root","session_id":"session-1","instance_id":"{{InstanceId}}","server_version":"0.4.276","discovery_path":"C:\\root\\native\\endpoint.json"}""";

    private sealed class ImmediateSynchronizationContext : SynchronizationContext
    {
        public override void Post(SendOrPostCallback callback, object? state) => callback(state);
    }

}
