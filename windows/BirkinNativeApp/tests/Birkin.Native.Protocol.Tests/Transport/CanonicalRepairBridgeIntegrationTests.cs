using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Tests.Support;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Commands;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Transport;

/// <summary>
/// Canonical repair must end in a replacement snapshot the real Python
/// bridge sends, not in a retained-event replay the store refuses while it
/// is replaying. These tests drive the real bridge over loopback.
/// </summary>
[TestClass]
[TestCategory("LiveBridge")]
public sealed class CanonicalRepairBridgeIntegrationTests
{
    [TestMethod]
    public async Task HeartbeatRepair_AtCurrentCursor_ReceivesRealSnapshotAndRestoresMutations()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(60));
        var started = await RealBridgeHarness.StartAsync(deadline.Token);
        await using var bridge = started.Harness;
        var store = new NativeProjectionStore();
        await using var session = new BridgeSession(store);
        await session.ConnectAsync(started.Announcement, started.Announcement.ServerVersion, deadline.Token);
        var initial = Current(store);
        var repairRequests = session.CanonicalRepairRequestCount;

        var replacement = new TaskCompletionSource<NativeProjectionState>(TaskCreationOptions.RunContinuationsAsynchronously);
        var transitions = new List<NativeProjectionRecoveryState>();
        var authority = new List<bool>();
        void OnSnapshot(NativeProjectionState state)
        {
            if (state.Cursor == initial.Cursor && state.ResetReason == "initial")
            {
                replacement.TrySetResult(state);
            }
        }
        void OnRecovery(NativeProjectionRecoveryState state)
        {
            lock (transitions) { transitions.Add(state); }
        }
        void OnAuthority(bool available)
        {
            lock (authority) { authority.Add(available); }
        }

        store.SnapshotApplied += OnSnapshot;
        store.RecoveryStateChanged += OnRecovery;
        store.MutationAuthorityChanged += OnAuthority;
        try
        {
            await session.ReportHeartbeatMissAsync(deadline.Token);
            var repaired = await replacement.Task.WaitAsync(deadline.Token);

            Assert.AreEqual(initial.SessionId, repaired.SessionId);
            Assert.AreEqual(initial.InstanceId, repaired.InstanceId);
            Assert.AreEqual(initial.Cursor, repaired.Cursor);
            Assert.AreEqual("initial", repaired.ResetReason);
            Assert.AreEqual(NativeProjectionStoreStatus.Current, store.Status);
            Assert.AreEqual(NativeProjectionRecoveryState.Live, store.RecoveryState);
            Assert.IsNull(store.RepairReason);
            Assert.IsTrue(store.IsMutationAuthorityAvailable);
            Assert.AreEqual(repairRequests + 1, session.CanonicalRepairRequestCount);
            lock (transitions)
            {
                CollectionAssert.AreEqual(
                    new[]
                    {
                        NativeProjectionRecoveryState.GapDetected,
                        NativeProjectionRecoveryState.ReplayInFlight,
                        NativeProjectionRecoveryState.Live,
                    },
                    transitions.ToArray());
            }
            lock (authority)
            {
                CollectionAssert.Contains(authority, false);
                CollectionAssert.Contains(authority, true);
                Assert.IsTrue(authority.Last());
            }

            await AssertRenameRoundTripAsync(session, store, repaired.Cursor, deadline.Token);
            Assert.AreEqual(1, session.MaximumConcurrentReceives);
        }
        finally
        {
            store.SnapshotApplied -= OnSnapshot;
            store.RecoveryStateChanged -= OnRecovery;
            store.MutationAuthorityChanged -= OnAuthority;
        }
    }

    [TestMethod]
    public async Task HeartbeatRepair_WithRetainedEvents_ReceivesRealSnapshotAndRestoresMutations()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(180));
        var started = await RealBridgeHarness.StartAsync(deadline.Token);
        await using var bridge = started.Harness;
        var store = new NativeProjectionStore();
        await using var session = new BridgeSession(store);
        await session.ConnectAsync(started.Announcement, started.Announcement.ServerVersion, deadline.Token);
        var identity = new NativeReadyIdentity(
            started.Announcement.SessionId,
            started.Announcement.InstanceId,
            started.Announcement.ServerVersion);
        var initial = Current(store);
        var initialCursor = initial.Cursor;

        var firstCommand = $"repair-warmup-{Guid.NewGuid():N}";
        var firstEvents = await SendAndAwaitEventsAsync(
            session,
            store,
            SessionCommands.Rename(identity.SessionId, UniqueName(), Context(firstCommand, store)),
            ["session.renamed", "command.completed"],
            deadline.Token);
        var renamedCursor = Current(store).Cursor;
        Assert.IsTrue(renamedCursor > initialCursor);
        CollectionAssert.AreEqual(
            Enumerable.Range((int)initialCursor + 1, (int)renamedCursor - (int)initialCursor).Select(value => (long)value).ToArray(),
            firstEvents.Select(envelope => ((NativeJsonInteger)envelope.Body["cursor"]!).Value).ToArray());

        store.ApplySnapshot(SnapshotOf(initial), identity);
        Assert.AreEqual(initialCursor, Current(store).Cursor);
        Assert.AreEqual(initial.SessionId, Current(store).SessionId);
        Assert.AreEqual(initial.InstanceId, Current(store).InstanceId);
        var repairRequests = session.CanonicalRepairRequestCount;

        var replacement = new TaskCompletionSource<NativeProjectionState>(TaskCreationOptions.RunContinuationsAsynchronously);
        var transitions = new List<NativeProjectionRecoveryState>();
        var authority = new List<bool>();
        void OnSnapshot(NativeProjectionState state)
        {
            if (state.Cursor == renamedCursor)
            {
                replacement.TrySetResult(state);
            }
        }
        void OnRecovery(NativeProjectionRecoveryState state)
        {
            lock (transitions) { transitions.Add(state); }
        }
        void OnAuthority(bool available)
        {
            lock (authority) { authority.Add(available); }
        }

        store.SnapshotApplied += OnSnapshot;
        store.RecoveryStateChanged += OnRecovery;
        store.MutationAuthorityChanged += OnAuthority;
        try
        {
            await session.ReportHeartbeatMissAsync(deadline.Token);
            var repaired = await replacement.Task.WaitAsync(deadline.Token);
            Assert.AreEqual(initial.SessionId, repaired.SessionId);
            Assert.AreEqual(initial.InstanceId, repaired.InstanceId);
            Assert.AreEqual(renamedCursor, repaired.Cursor);
            Assert.AreEqual("initial", repaired.ResetReason);
            Assert.AreEqual(NativeProjectionRecoveryState.Live, store.RecoveryState);
            Assert.IsNull(store.RepairReason);
            Assert.IsTrue(store.IsMutationAuthorityAvailable);
            Assert.AreEqual(repairRequests + 1, session.CanonicalRepairRequestCount);
            Assert.IsTrue(
                SessionNames(repaired).Contains(identity.SessionId),
                "the replacement snapshot must carry the current session history");
            lock (transitions)
            {
                CollectionAssert.AreEqual(
                    new[]
                    {
                        NativeProjectionRecoveryState.GapDetected,
                        NativeProjectionRecoveryState.ReplayInFlight,
                        NativeProjectionRecoveryState.Live,
                    },
                    transitions.ToArray());
            }
            lock (authority)
            {
                Assert.IsTrue(authority.Last());
            }

            await AssertRenameRoundTripAsync(session, store, repaired.Cursor, deadline.Token);
            Assert.AreEqual(1, session.MaximumConcurrentReceives);
        }
        finally
        {
            store.SnapshotApplied -= OnSnapshot;
            store.RecoveryStateChanged -= OnRecovery;
            store.MutationAuthorityChanged -= OnAuthority;
        }
    }

    private static async Task AssertRenameRoundTripAsync(
        BridgeSession session,
        NativeProjectionStore store,
        long cursor,
        CancellationToken cancellationToken)
    {
        var name = UniqueName();
        var commandId = $"repair-verify-{Guid.NewGuid():N}";
        var renameCursor = store.State?.Cursor
            ?? throw new AssertFailedException("projection state is unavailable before rename");
        var events = await SendAndAwaitEventsAsync(
            session,
            store,
            SessionCommands.Rename(Current(store).SessionId, name, new CommandRequestContext(
                commandId,
                renameCursor,
                NativeHandshake.ViewId)),
            ["session.renamed", "command.completed"],
            cancellationToken);
        Assert.AreEqual(cursor, renameCursor);
        var renamed = events.Single(envelope =>
            envelope.Body["type"] is NativeJsonString type
            && string.Equals(type.Value, "session.renamed", StringComparison.Ordinal));
        Assert.AreEqual(name, ((NativeJsonString)((NativeJsonObject)renamed.Body["payload"]!)["name"]!).Value);
        Assert.IsTrue(
            SessionNames(Current(store)).Contains(Current(store).SessionId),
            "the repaired projection must keep the current session history");
    }

    private static async Task<List<NativeEnvelope>> SendAndAwaitEventsAsync(
        BridgeSession session,
        NativeProjectionStore store,
        NativeCommandRequest request,
        IReadOnlyCollection<string> expectedTypes,
        CancellationToken cancellationToken)
    {
        var remaining = new HashSet<string>(expectedTypes, StringComparer.Ordinal);
        var captured = new List<NativeEnvelope>();
        var applied = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        void OnApplied(NativeEnvelope envelope)
        {
            if (envelope.Kind != NativeMessageKind.Event
                || envelope.Body["command_id"] is not NativeJsonString commandId
                || !string.Equals(commandId.Value, request.CommandId, StringComparison.Ordinal)
                || envelope.Body["type"] is not NativeJsonString type)
            {
                return;
            }
            lock (captured) { captured.Add(envelope); }
            if (string.Equals(type.Value, "command.failed", StringComparison.Ordinal))
            {
                applied.TrySetException(new AssertFailedException(
                    $"Command {request.CommandId} failed: "
                    + System.Text.Encoding.UTF8.GetString(
                        NativeJsonSerializer.Serialize(envelope.ToJsonValue()))));
                return;
            }
            if (remaining.Remove(type.Value) && remaining.Count == 0)
            {
                applied.TrySetResult();
            }
        }

        store.CanonicalApplied += OnApplied;
        try
        {
            var receiptTask = session.SendCommandForResultAsync(request, cancellationToken).AsTask();
            await applied.Task.WaitAsync(cancellationToken);
            var receipt = await receiptTask.WaitAsync(cancellationToken);
            Assert.AreEqual("completed", ((NativeJsonString)receipt.Body["state"]!).Value);
            return captured;
        }
        finally
        {
            store.CanonicalApplied -= OnApplied;
        }
    }

    private static CommandRequestContext Context(string commandId, NativeProjectionStore store) =>
        new(commandId, Current(store).Cursor, NativeHandshake.ViewId);

    private static NativeProjectionState Current(NativeProjectionStore store) =>
        store.State ?? throw new AssertFailedException("projection state is unavailable");

    private static NativeEnvelope SnapshotOf(NativeProjectionState state) => new(
        NativeMessageKind.Snapshot,
        "stale-client-snapshot",
        new NativeJsonObject(state.ToBody().Pairs.Concat([
            new KeyValuePair<string, NativeJsonValue>("instance_id", new NativeJsonString(state.InstanceId)),
            new KeyValuePair<string, NativeJsonValue>("reset_reason", new NativeJsonString(state.ResetReason)),
        ])));

    private static string UniqueName() => $"repair-{Guid.NewGuid():N}";

    private static string[] SessionNames(NativeProjectionState state) => SessionsPanel(state)
        .Where(item => item["session_id"] is NativeJsonString)
        .Select(item => ((NativeJsonString)item["session_id"]!).Value)
        .ToArray();

    private static string[] SessionRenames(NativeProjectionState state) => SessionsPanel(state)
        .Where(item => item["status"] is NativeJsonString status
            && string.Equals(status.Value, "renamed", StringComparison.Ordinal)
            && item["session_id"] is NativeJsonString)
        .Select(item => ((NativeJsonString)item["session_id"]!).Value)
        .ToArray();

    private static NativeJsonObject[] SessionsPanel(NativeProjectionState state) => ((NativeJsonArray)state.Panels
        .Values.Cast<NativeJsonObject>()
        .Single(panel => ((NativeJsonString)panel["key"]!).Value == "sessions_history")["items"]!) .Values
        .Cast<NativeJsonObject>()
        .ToArray();
}
