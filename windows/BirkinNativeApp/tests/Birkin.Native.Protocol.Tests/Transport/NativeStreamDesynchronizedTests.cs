using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Tests.Messaging;
using Birkin.Native.Protocol.Tests.Support;
using Birkin.Native.Protocol.Transport;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Transport;

[TestClass]
public sealed class NativeStreamDesynchronizedTests
{
    [TestMethod]
    public async Task ReceiveAsync_WhenStreamDesynchronizes_RequestsCanonicalRepairFromResumeCursor()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        var store = new NativeProjectionStore();
        await using var connection = new NativeClientConnection(store);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var connecting = connection.ConnectAsync(discovery.Announcement, TestDiscovery.Version, deadline.Token);
        var hello = await server.ReceiveAsync();
        await server.SendAsync(NativeHandshakeTests.Ready(hello.Id));
        await connecting;
        _ = await server.ReceiveAsync();
        store.ApplySnapshot(Snapshot(), new NativeReadyIdentity("native-app", TestDiscovery.InstanceId, TestDiscovery.Version));
        var signal = new NativeEnvelope(NativeMessageKind.StreamDesynchronized, "desynchronized-1", Object(
            ("resume_after", new NativeJsonInteger(7))));
        var receiving = connection.ReceiveAsync(deadline.Token).AsTask();

        // When
        await server.SendAsync(signal);
        _ = await receiving;
        var repair = await server.ReceiveAsync();

        // Then
        Assert.AreEqual(NativeMessageKind.Subscribe, repair.Kind);
        Assert.AreEqual(7L, Integer(repair.Body, "after_cursor"));
        Assert.AreEqual("capability-token", String(repair.Body, "session_capability"));
        Assert.AreEqual(NativeProjectionRepairReason.StreamDesynchronized, store.RepairReason);
        Assert.IsTrue(((NativeJsonObject)repair.Body["surfaces"]!).Pairs.All(pair => ((NativeJsonInteger)pair.Value).Value == 0));
    }

    private static NativeEnvelope Snapshot() => new(
        NativeMessageKind.Snapshot,
        "snapshot-before-desync",
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("session_id", new NativeJsonString("native-app")),
            ("cursor", new NativeJsonInteger(7)),
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
