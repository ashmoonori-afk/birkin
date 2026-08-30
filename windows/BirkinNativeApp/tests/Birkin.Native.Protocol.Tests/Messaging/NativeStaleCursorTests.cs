using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Tests.Support;
using Birkin.Native.Protocol.Transport;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Messaging;

[TestClass]
public sealed class NativeStaleCursorTests
{
    [TestMethod]
    public async Task ReceiveAsync_WhenStaleCursorCorrelates_ReturnsTypedRefusalWithoutRetry()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await server.CompleteHandshakeAsync(connection, discovery, deadline.Token);
        var request = Request("stale-command", 4);
        await connection.SendCommandAsync(request, deadline.Token);
        var command = await server.ReceiveAsync();
        var receiving = connection.ReceiveAsync(deadline.Token).AsTask();

        // When
        await server.SendAsync(Stale("stale-error", command.Id, 9));
        var refusal = await Assert.ThrowsExceptionAsync<NativeCommandRefusal>(() => receiving);
        await connection.SendCommandAsync(Request("caller-decides-next", 9), deadline.Token);
        var nextWritten = await server.ReceiveAsync();

        // Then
        Assert.AreEqual("E_STALE_CURSOR", refusal.Code);
        Assert.AreEqual("stale-command", refusal.CommandId);
        Assert.AreEqual(9L, refusal.CurrentCursor);
        Assert.AreEqual("bounded refusal", refusal.Message);
        Assert.IsFalse(refusal.Retryable);
        Assert.AreEqual("caller-decides-next", String(Object(nextWritten.Body, "command"), "command_id"));
    }

    [TestMethod]
    public async Task ReceiveAsync_WhenStaleCursorFrameDoesNotCorrelate_RetainsPendingCommand()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await server.CompleteHandshakeAsync(connection, discovery, deadline.Token);
        await connection.SendCommandAsync(Request("still-pending", 2), deadline.Token);
        _ = await server.ReceiveAsync();
        var receiving = connection.ReceiveAsync(deadline.Token).AsTask();

        // When
        await server.SendAsync(Stale("wrong-stale", "unknown-frame", 8));
        var correlation = await Assert.ThrowsExceptionAsync<NativeProtocolError>(() => receiving);
        var flow = await Assert.ThrowsExceptionAsync<NativeProtocolError>(
            () => connection.SendCommandAsync(Request("must-not-cross", 8), deadline.Token).AsTask());

        // Then
        Assert.AreEqual("E_CORRELATION", correlation.Code);
        Assert.AreEqual("E_FLOW_VIOLATION", flow.Code);
    }

    private static NativeCommandRequest Request(string commandId, long expectedCursor) => new(
        new NativeCommandIdentity(commandId, expectedCursor),
        new NativeCommandIntent(
            "chat.send",
            Object(("text", new NativeJsonString("draft remains caller-owned")))),
        "conversation");

    private static NativeEnvelope Stale(string id, string reply, long currentCursor) => new(
        NativeMessageKind.Error,
        new NativeEnvelopeIdentity(id, reply),
        Object(
            ("code", new NativeJsonString("E_STALE_CURSOR")),
            ("message", new NativeJsonString("bounded refusal")),
            ("retryable", new NativeJsonBoolean(false)),
            ("current_cursor", new NativeJsonInteger(currentCursor))));

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));

    private static NativeJsonObject Object(NativeJsonObject body, string key) =>
        body[key] as NativeJsonObject ?? throw new AssertFailedException($"{key} is not an object");

    private static string String(NativeJsonObject body, string key) =>
        body[key] is NativeJsonString text ? text.Value : throw new AssertFailedException($"{key} is not a string");
}
