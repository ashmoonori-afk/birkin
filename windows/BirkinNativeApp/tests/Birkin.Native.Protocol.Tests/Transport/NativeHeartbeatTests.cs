using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Tests.Messaging;
using Birkin.Native.Protocol.Tests.Support;
using Birkin.Native.Protocol.Transport;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Transport;

[TestClass]
public sealed class NativeHeartbeatTests
{
    [TestMethod]
    public async Task ReceiveAsync_WhenServerSendsAsymmetricPing_AnswersWithAuthenticatedPong()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var connecting = connection.ConnectAsync(discovery.Announcement, TestDiscovery.Version, deadline.Token);
        var hello = await server.ReceiveAsync();
        await server.SendAsync(NativeHandshakeTests.Ready(hello.Id));
        await connecting;
        _ = await server.ReceiveAsync();
        const string sentAt = "2026-08-24T02:45:00+00:00";
        var ping = new NativeEnvelope(NativeMessageKind.Ping, "server-ping-1", Object(
            ("sent_at", new NativeJsonString(sentAt))));
        var receiving = connection.ReceiveAsync(deadline.Token).AsTask();

        // When
        await server.SendAsync(ping);
        _ = await receiving;
        var pong = await server.ReceiveAsync();

        // Then
        Assert.AreEqual(NativeMessageKind.Pong, pong.Kind);
        Assert.AreEqual(ping.Id, pong.InReplyTo);
        Assert.AreEqual(sentAt, String(pong.Body, "sent_at"));
        Assert.AreEqual("capability-token", String(pong.Body, "session_capability"));
        NativeBodyValidator.Validate(pong, NativeMessageOrigin.Client);
    }

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));

    private static string String(NativeJsonObject body, string key) => ((NativeJsonString)body[key]!).Value;
}
