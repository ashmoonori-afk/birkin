using System.Reflection;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Tests.Support;
using Birkin.Native.Protocol.Transport;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Transport;

[TestClass]
public sealed class NativeCapabilityRenewalTests
{
    [TestMethod]
    public async Task ReceiveAsync_WhenCapabilityIsRenewed_SelectsOnlyRenewedCapabilityForNewFrame()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await server.CompleteHandshakeAsync(connection, discovery, deadline.Token);
        var renewal = new NativeEnvelope(NativeMessageKind.CapabilityRenewed, "renewal-1", Object(
            ("token", new NativeJsonString("renewed-capability")),
            ("expires_at", new NativeJsonString("2026-08-24T03:00:00+00:00")),
            ("hard_expires_at", new NativeJsonString("2026-08-24T08:00:00+00:00"))));
        var receivingRenewal = connection.ReceiveAsync(deadline.Token).AsTask();
        await server.SendAsync(renewal);
        _ = await receivingRenewal;
        var secondRenewal = new NativeEnvelope(NativeMessageKind.CapabilityRenewed, "renewal-2", Object(
            ("token", new NativeJsonString("latest-capability")),
            ("expires_at", new NativeJsonString("2026-08-24T04:00:00+00:00")),
            ("hard_expires_at", new NativeJsonString("2026-08-24T08:00:00+00:00"))));
        var receivingSecondRenewal = connection.ReceiveAsync(deadline.Token).AsTask();
        await server.SendAsync(secondRenewal);
        _ = await receivingSecondRenewal;
        var ping = new NativeEnvelope(NativeMessageKind.Ping, "ping-after-renewal", Object(
            ("sent_at", new NativeJsonString("2026-08-24T02:45:00+00:00"))));
        var receivingPing = connection.ReceiveAsync(deadline.Token).AsTask();

        // When
        await server.SendAsync(ping);
        _ = await receivingPing;
        var pong = await server.ReceiveAsync();

        // Then
        Assert.AreEqual("latest-capability", String(pong.Body, "session_capability"));
        Assert.AreEqual("renewed-capability", connection.PredecessorCapability?.Token);
        Assert.AreEqual("latest-capability", connection.CurrentCapability?.Token);
    }

    [DataTestMethod]
    [DataRow("goodbye")]
    [DataRow("expired")]
    public async Task ReceiveAsync_WhenAuthorityEnds_ClearsCurrentAndPredecessor(string ending)
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await server.CompleteHandshakeAsync(connection, discovery, deadline.Token);
        var renewal = new NativeEnvelope(NativeMessageKind.CapabilityRenewed, "renewal-before-end", Object(
            ("token", new NativeJsonString("renewed-capability")),
            ("expires_at", new NativeJsonString("2026-08-24T03:00:00+00:00")),
            ("hard_expires_at", new NativeJsonString("2026-08-24T08:00:00+00:00"))));
        var receivingRenewal = connection.ReceiveAsync(deadline.Token).AsTask();
        await server.SendAsync(renewal);
        _ = await receivingRenewal;
        var endingFrame = ending == "goodbye"
            ? new NativeEnvelope(NativeMessageKind.Goodbye, "goodbye-1", Object(
                ("reason", new NativeJsonString("shutdown"))))
            : new NativeEnvelope(NativeMessageKind.Error, "expired-1", Object(
                ("code", new NativeJsonString("E_CAPABILITY_EXPIRED")),
                ("message", new NativeJsonString("not asserted")),
                ("retryable", new NativeJsonBoolean(false))));
        var receivingEnding = connection.ReceiveAsync(deadline.Token).AsTask();

        // When
        await server.SendAsync(endingFrame);
        _ = await receivingEnding;

        // Then
        Assert.IsNull(connection.CurrentCapability);
        Assert.IsNull(connection.PredecessorCapability);
    }

    [DataTestMethod]
    [DataRow("repair")]
    [DataRow("switch")]
    public async Task Subscribe_AfterTwoRenewals_UsesLatestCapabilityAndCorrectIdentity(string path)
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await server.CompleteHandshakeAsync(connection, discovery, deadline.Token);
        await RenewOnceAsync(connection, server, "renewal-1", "renewed-capability", deadline.Token);
        await RenewOnceAsync(connection, server, "renewal-2", "latest-capability", deadline.Token);
        var invoking = path == "repair"
            ? InvokeAsync(connection, "RequestCanonicalReplayAsync", 42L, deadline.Token)
            : InvokeAsync(connection, "SwitchSessionAsync", "switched-app", deadline.Token);
        var receivingSubscribe = server.ReceiveAsync();

        // When
        await invoking;
        var subscribe = await receivingSubscribe;

        // Then
        Assert.AreEqual("subscribe", subscribe.Kind.WireName);
        Assert.AreEqual("latest-capability", String(subscribe.Body, "session_capability"));
        Assert.AreEqual(
            path == "repair" ? "native-app" : "switched-app",
            String(subscribe.Body, "session_id"));
        Assert.AreEqual(
            path == "repair" ? 42L : 0L,
            ((NativeJsonInteger)subscribe.Body["after_cursor"]!).Value);
        if (path == "repair")
        {
            Assert.AreEqual(TestDiscovery.InstanceId, String(subscribe.Body, "known_instance_id"));
        }
        else
        {
            Assert.IsInstanceOfType<NativeJsonNull>(subscribe.Body["known_instance_id"]);
        }
    }

    private static async Task RenewOnceAsync(
        NativeClientConnection connection,
        LoopbackServerHarness server,
        string frameId,
        string token,
        CancellationToken cancellationToken)
    {
        var renewal = new NativeEnvelope(NativeMessageKind.CapabilityRenewed, frameId, Object(
            ("token", new NativeJsonString(token)),
            ("expires_at", new NativeJsonString("2026-08-24T03:00:00+00:00")),
            ("hard_expires_at", new NativeJsonString("2026-08-24T08:00:00+00:00"))));
        var receivingRenewal = connection.ReceiveAsync(cancellationToken).AsTask();
        await server.SendAsync(renewal);
        _ = await receivingRenewal;
    }

    private static Task InvokeAsync(object target, string method, params object[] arguments) =>
        ((ValueTask)target.GetType()
            .GetMethod(method, BindingFlags.Instance | BindingFlags.NonPublic)!
            .Invoke(target, arguments)!).AsTask();

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));

    private static string String(NativeJsonObject body, string key) => ((NativeJsonString)body[key]!).Value;
}
