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
public sealed partial class BridgeSessionTests
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

}
