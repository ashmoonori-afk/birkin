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
    public async Task SendCommandForResultAsync_WhenPythonReportsNewerStaleCursor_RepairsBeforeNextMutation()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        var store = new NativeProjectionStore();
        await using var session = new BridgeSession(store);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await ConnectAndSnapshotAsync(server, discovery, session, deadline.Token);
        var repairStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        store.RecoveryStateChanged += state =>
        {
            if (state == NativeProjectionRecoveryState.ReplayInFlight) repairStarted.TrySetResult();
        };
        var result = session.SendCommandForResultAsync(Request("stale-command"), deadline.Token).AsTask();
        var command = await server.ReceiveAsync();

        // When
        await server.SendAsync(Stale("stale-refusal", command.Id, currentCursor: 1));
        var refusal = await Assert.ThrowsExceptionAsync<NativeCommandRefusal>(() => result);
        await repairStarted.Task.WaitAsync(deadline.Token);
        var replay = await server.ReceiveAsync();
        var replaced = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        store.SnapshotApplied += _ => replaced.TrySetResult();
        await server.SendAsync(Snapshot("stale-replacement", cursor: 1));
        await replaced.Task.WaitAsync(deadline.Token);

        // Then
        Assert.AreEqual("E_STALE_CURSOR", refusal.Code);
        Assert.AreEqual(NativeMessageKind.Subscribe, replay.Kind);
        Assert.AreEqual(0L, ((NativeJsonInteger)replay.Body["after_cursor"]!).Value);
        Assert.AreEqual(1L, store.State?.Cursor);
        Assert.IsTrue(store.IsMutationAuthorityAvailable);
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

}
