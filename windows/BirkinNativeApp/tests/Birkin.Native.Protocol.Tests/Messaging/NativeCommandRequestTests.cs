using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Tests.Support;
using Birkin.Native.Protocol.Transport;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Messaging;

[TestClass]
public sealed class NativeCommandRequestTests
{
    [TestMethod]
    public async Task SendCommandAsync_WhenRequestIsTyped_WritesExactPythonCommandShape()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await server.CompleteHandshakeAsync(connection, discovery, deadline.Token);
        var request = Request("stable-command-1", 44);

        // When
        await connection.SendCommandAsync(request, deadline.Token);
        var envelope = await server.ReceiveAsync();

        // Then
        Assert.AreEqual(NativeMessageKind.Command, envelope.Kind);
        Assert.AreNotEqual(request.CommandId, envelope.Id);
        Assert.IsNull(envelope.InReplyTo);
        Assert.AreEqual("capability-token", String(envelope.Body, "session_capability"));
        var command = Object(envelope.Body, "command");
        Assert.AreEqual(1L, Integer(command, "protocol_version"));
        Assert.AreEqual("stable-command-1", String(command, "command_id"));
        Assert.AreEqual(44L, Integer(command, "expected_cursor"));
        Assert.AreEqual("chat.send", String(command, "type"));
        Assert.AreEqual("hello", String(Object(command, "payload"), "text"));
        var context = Object(command, "client_context");
        Assert.AreEqual("windows", String(context, "surface"));
        Assert.AreEqual("conversation", String(context, "view_id"));
    }

    [TestMethod]
    public async Task SendCommandAsync_WhenSameIntentIsResent_PreservesStableCommandId()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await server.CompleteHandshakeAsync(connection, discovery, deadline.Token);
        var request = Request("stable-retry-1", 7);
        await connection.SendCommandAsync(request, deadline.Token);
        var first = await server.ReceiveAsync();
        var receiving = connection.ReceiveAsync(deadline.Token).AsTask();
        await server.SendAsync(Receipt("receipt-first", first.Id, request.CommandId));
        _ = await receiving;

        // When
        await connection.SendCommandAsync(request, deadline.Token);
        var second = await server.ReceiveAsync();

        // Then
        Assert.AreNotEqual(first.Id, second.Id);
        Assert.AreEqual("stable-retry-1", String(Object(first.Body, "command"), "command_id"));
        Assert.AreEqual("stable-retry-1", String(Object(second.Body, "command"), "command_id"));
        Assert.AreEqual(7L, Integer(Object(second.Body, "command"), "expected_cursor"));
    }

    [TestMethod]
    public async Task SendCommandAsync_WhenOneCommandIsPending_RefusesSecondBeforeTransportWrite()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await server.CompleteHandshakeAsync(connection, discovery, deadline.Token);
        await connection.SendCommandAsync(Request("pending-1", 0), deadline.Token);
        var first = await server.ReceiveAsync();

        // When
        var error = await Assert.ThrowsExceptionAsync<NativeProtocolError>(
            () => connection.SendCommandAsync(Request("blocked-2", 0), deadline.Token).AsTask());
        var receiving = connection.ReceiveAsync(deadline.Token).AsTask();
        await server.SendAsync(Receipt("receipt-pending", first.Id, "pending-1"));
        _ = await receiving;
        await connection.SendCommandAsync(Request("after-release-3", 1), deadline.Token);
        var nextWritten = await server.ReceiveAsync();

        // Then
        Assert.AreEqual("E_FLOW_VIOLATION", error.Code);
        Assert.AreEqual("after-release-3", String(Object(nextWritten.Body, "command"), "command_id"));
    }

    private static NativeCommandRequest Request(string commandId, long expectedCursor) => new(
        new NativeCommandIdentity(commandId, expectedCursor),
        new NativeCommandIntent("chat.send", Object(("text", new NativeJsonString("hello")))),
        "conversation");

    private static NativeEnvelope Receipt(string id, string reply, string commandId) => new(
        NativeMessageKind.Receipt,
        new NativeEnvelopeIdentity(id, reply),
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("command_id", new NativeJsonString(commandId)),
            ("session_id", new NativeJsonString("native-app")),
            ("actor_id", new NativeJsonString("windows:conversation")),
            ("accepted_cursor", new NativeJsonInteger(1)),
            ("state", new NativeJsonString("completed")),
            ("result_event_cursor", new NativeJsonInteger(3)),
            ("duplicate", new NativeJsonBoolean(false)),
            ("outcome", new NativeJsonString("accepted"))));

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));

    private static NativeJsonObject Object(NativeJsonObject body, string key) =>
        body[key] as NativeJsonObject ?? throw new AssertFailedException($"{key} is not an object");

    private static string String(NativeJsonObject body, string key) =>
        body[key] is NativeJsonString text ? text.Value : throw new AssertFailedException($"{key} is not a string");

    private static long Integer(NativeJsonObject body, string key) =>
        body[key] is NativeJsonInteger integer ? integer.Value : throw new AssertFailedException($"{key} is not an integer");
}
