using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Tests.Messaging;
using Birkin.Native.Protocol.Tests.Support;
using Birkin.Native.Protocol.Transport;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Transport;

[TestClass]
public sealed class NativeConnectionReconnectTests
{
    [TestMethod]
    public async Task ReceiveAsync_WhenTransportDisconnects_ClearsAuthorityBeforeReplayReconnect()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        var store = new NativeProjectionStore();
        var scheduled = new TaskCompletionSource<TimeSpan>(TaskCreationOptions.RunContinuationsAsynchronously);
        ValueTask Schedule(TimeSpan delay, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            scheduled.TrySetResult(delay);
            return ValueTask.CompletedTask;
        }
        await using var connection = new NativeClientConnection(store, Schedule, () => 0.5);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await server.CompleteHandshakeAsync(connection, discovery, deadline.Token);
        var renewal = new NativeEnvelope(NativeMessageKind.CapabilityRenewed, "renewal-before-disconnect", Object(
            ("token", new NativeJsonString("renewed-before-disconnect")),
            ("expires_at", new NativeJsonString("2026-08-24T03:00:00+00:00")),
            ("hard_expires_at", new NativeJsonString("2026-08-24T08:00:00+00:00"))));
        var receivingRenewal = connection.ReceiveAsync(deadline.Token).AsTask();
        await server.SendAsync(renewal);
        _ = await receivingRenewal;
        store.ApplySnapshot(Snapshot(7), new NativeReadyIdentity("native-app", TestDiscovery.InstanceId, TestDiscovery.Version));
        discovery.Refresh(server.Port);
        var receiving = connection.ReceiveAsync(deadline.Token).AsTask();

        // When
        await server.DisconnectClientAsync();
        var delay = await scheduled.Task.WaitAsync(deadline.Token);
        var reconnectHello = await server.ReceiveAsync();

        // Then
        Assert.AreEqual(TimeSpan.FromMilliseconds(250), delay);
        Assert.IsNull(connection.CurrentCapability);
        Assert.IsNull(connection.PredecessorCapability);
        Assert.IsFalse(connection.IsProjectionCurrent);
        await server.SendAsync(NativeHandshakeTests.Ready(reconnectHello.Id));
        var subscribe = await server.ReceiveAsync();
        Assert.AreEqual(7L, Integer(subscribe.Body, "after_cursor"));
        Assert.AreEqual(TestDiscovery.InstanceId, String(subscribe.Body, "known_instance_id"));
        var ping = new NativeEnvelope(NativeMessageKind.Ping, "reconnected-ping", Object(
            ("sent_at", new NativeJsonString("2026-08-24T02:45:00+00:00"))));
        await server.SendAsync(ping);
        _ = await receiving;
        _ = await server.ReceiveAsync();
    }

    [DataTestMethod]
    [DataRow(0, 250)]
    [DataRow(1, 500)]
    [DataRow(2, 1000)]
    [DataRow(3, 2000)]
    [DataRow(4, 5000)]
    [DataRow(8, 5000)]
    public void ReconnectDelay_WhenAttemptIncreases_IsBounded(int attempt, int expectedMilliseconds)
    {
        // Given / When
        var delay = NativeClientConnection.ReconnectDelay(attempt, 0.5);

        // Then
        Assert.AreEqual(TimeSpan.FromMilliseconds(expectedMilliseconds), delay);
    }

    private static NativeEnvelope Snapshot(long cursor) => new(
        NativeMessageKind.Snapshot,
        "snapshot-before-disconnect",
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("session_id", new NativeJsonString("native-app")),
            ("cursor", new NativeJsonInteger(cursor)),
            ("panels", new NativeJsonArray([])),
            ("conversation", new NativeJsonArray([])),
            ("composer", Object()),
            ("status", Object()),
            ("working_memory", Object()),
            ("approval_policy", Object()),
            ("terminals", new NativeJsonArray([])),
            ("instance_id", new NativeJsonString(TestDiscovery.InstanceId)),
            ("reset_reason", new NativeJsonString("initial"))));

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));

    private static string String(NativeJsonObject body, string key) => ((NativeJsonString)body[key]!).Value;

    private static long Integer(NativeJsonObject body, string key) => ((NativeJsonInteger)body[key]!).Value;
}
