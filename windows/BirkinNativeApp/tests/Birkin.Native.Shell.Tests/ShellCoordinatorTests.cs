using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests;

[TestClass]
public sealed class ShellCoordinatorTests
{
    private const string ExpectedProductVersion = "independent-client-version";
    private const string InstanceId = "0123456789abcdef0123456789abcdef";

    [TestMethod]
    public async Task ConnectAsync_WhenValidatedSnapshotArrives_PublishesUiReadyPresentationAfterStateSequence()
    {
        // Given
        var frame = NativeFrameCodec.Encode(SnapshotEnvelope());
        await using var connection = new FrameConnection(NativeFrameCodec.Decode(frame));
        var store = new NativeProjectionStore();
        var context = new DeterministicSynchronizationContext();
        var model = new ShellPresentationModel(context);
        await using var coordinator = new ShellCoordinator(connection, store, model);
        var states = new List<ConnectionState>();
        coordinator.ConnectionStateChanged += states.Add;
        var applied = new TaskCompletionSource<WorkspaceSnapshotPresentation>(TaskCreationOptions.RunContinuationsAsynchronously);
        coordinator.SnapshotApplied += snapshot => applied.TrySetResult(snapshot);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));

        // When
        await coordinator.ConnectAsync(AnnouncementJson(), ExpectedProductVersion, deadline.Token);
        context.RunAll();
        var presentation = await applied.Task.WaitAsync(deadline.Token);

        // Then
        CollectionAssert.AreEqual(
            new[] { ConnectionState.Connecting, ConnectionState.Handshaking, ConnectionState.Subscribing, ConnectionState.Ready },
            states);
        Assert.AreEqual(ExpectedProductVersion, connection.ExpectedProductVersion);
        Assert.AreEqual("session-1", connection.Announcement?.SessionId);
        Assert.IsNotNull(store.State);
        Assert.AreEqual(42L, store.State.Cursor);
        Assert.AreSame(presentation, model.Workspace);
        Assert.AreEqual(ConnectionState.Ready, model.Connection.State);
        Assert.AreEqual("LOCAL · PRIVATE", model.Connection.StatusText);
        Assert.AreEqual(1L, presentation.ProtocolVersion);
        Assert.AreEqual("session-1", presentation.SessionId);
        Assert.AreEqual(42L, presentation.Cursor);
        Assert.AreEqual(InstanceId, presentation.InstanceId);
        Assert.AreEqual("initial", presentation.ResetReason);
        Assert.AreEqual("loopback", presentation.Transport);
        Assert.AreEqual(2, presentation.PanelCount);
    }

    [TestMethod]
    public async Task ConnectAsync_WhenProtocolFails_PublishesBoundedFailureWithoutExceptionContent()
    {
        // Given
        const string recordContent = "bootstrap_secret=do-not-render; discovery=C:\\private\\endpoint.json";
        await using var connection = new FrameConnection(new NativeProtocolError("E_BOOTSTRAP_INVALID", recordContent));
        var context = new DeterministicSynchronizationContext();
        var model = new ShellPresentationModel(context);
        await using var coordinator = new ShellCoordinator(connection, new NativeProjectionStore(), model);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));

        // When
        await coordinator.ConnectAsync(AnnouncementJson(), ExpectedProductVersion, deadline.Token);
        context.RunAll();

        // Then
        Assert.AreEqual(ConnectionState.Failed, model.Connection.State);
        Assert.AreEqual("E_BOOTSTRAP_INVALID", model.Connection.ErrorCode);
        Assert.IsFalse(model.Connection.StatusText.Contains(recordContent, StringComparison.Ordinal));
        Assert.IsNull(model.Workspace);
    }

    private static NativeEnvelope SnapshotEnvelope() => new(
        NativeMessageKind.Snapshot,
        "server-snapshot-1",
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("session_id", new NativeJsonString("session-1")),
            ("cursor", new NativeJsonInteger(42)),
            ("panels", new NativeJsonArray([Object(), Object()])),
            ("conversation", new NativeJsonArray([])),
            ("composer", Object()),
            ("status", Object()),
            ("working_memory", Object()),
            ("approval_policy", Object()),
            ("terminals", new NativeJsonArray([])),
            ("instance_id", new NativeJsonString(InstanceId)),
            ("reset_reason", new NativeJsonString("initial"))));

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));

    private static string AnnouncementJson() => TestBridgeAnnouncement.Json(1904);

    private sealed class FrameConnection : INativeClientConnection
    {
        private readonly NativeEnvelope? _envelope;
        private readonly NativeProtocolError? _connectError;

        public FrameConnection(NativeEnvelope envelope) => _envelope = envelope;

        public FrameConnection(NativeProtocolError connectError) => _connectError = connectError;

        public BridgeAnnouncement? Announcement { get; private set; }

        public string? ExpectedProductVersion { get; private set; }

        public Task ConnectAsync(
            BridgeAnnouncement announcement,
            string expectedProductVersion,
            CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Announcement = announcement;
            ExpectedProductVersion = expectedProductVersion;
            return _connectError is null ? Task.CompletedTask : Task.FromException(_connectError);
        }

        public ValueTask<NativeEnvelope> ReceiveAsync(CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            return ValueTask.FromResult(_envelope ?? throw new InvalidOperationException());
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class DeterministicSynchronizationContext : SynchronizationContext
    {
        private readonly Queue<(SendOrPostCallback Callback, object? State)> _work = new();

        public override void Post(SendOrPostCallback d, object? state) => _work.Enqueue((d, state));

        public void RunAll()
        {
            while (_work.TryDequeue(out var work))
            {
                work.Callback(work.State);
            }
        }
    }
}
