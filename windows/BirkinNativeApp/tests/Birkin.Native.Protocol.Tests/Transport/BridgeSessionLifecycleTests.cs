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

public sealed partial class BridgeSessionTests
{
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

}
