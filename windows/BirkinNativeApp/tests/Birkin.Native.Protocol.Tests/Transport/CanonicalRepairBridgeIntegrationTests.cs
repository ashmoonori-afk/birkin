using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Tests.Support;
using Birkin.Native.Protocol.Transport;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Transport;

[TestClass]
[TestCategory("LiveBridge")]
[TestCategory("WindowsOnly")]
public sealed class CanonicalRepairBridgeIntegrationTests
{
    [TestMethod]
    public async Task HeartbeatRepair_AtCurrentCursor_ReceivesRealSnapshotAndRestoresMutations()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(60));
        var started = await RealBridgeHarness.StartAsync(deadline.Token);
        await using var bridge = started.Harness;
        var store = new NativeProjectionStore();
        await using var session = new BridgeSession(store);
        await session.ConnectAsync(started.Announcement, started.Announcement.ServerVersion, deadline.Token);
        var instanceId = store.State?.InstanceId;
        var cursor = store.State?.Cursor ?? throw new AssertFailedException("connect did not restore a projection snapshot");
        var snapshotApplied = new TaskCompletionSource<NativeProjectionState>(TaskCreationOptions.RunContinuationsAsynchronously);
        store.SnapshotApplied += state => snapshotApplied.TrySetResult(state);

        // When
        await session.ReportHeartbeatMissAsync(deadline.Token);
        var repaired = await snapshotApplied.Task.WaitAsync(deadline.Token);

        // Then
        Assert.AreEqual(instanceId, repaired.InstanceId);
        Assert.AreEqual(cursor, repaired.Cursor);
        Assert.AreEqual(NativeProjectionRecoveryState.Live, store.RecoveryState);
        Assert.AreEqual(NativeProjectionStoreStatus.Current, store.Status);
        Assert.IsNull(store.RepairReason);
        Assert.IsTrue(store.IsMutationAuthorityAvailable);
    }
}
