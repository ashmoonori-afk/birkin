using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Tests.Support;
using Birkin.Native.Protocol.Transport;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Messaging;

[TestClass]
public sealed class NativeReceiptTests
{
    [TestMethod]
    public async Task ReceiveAsync_WhenReceiptCorrelatesByFrameAndCommand_AcceptsExactlyOnce()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await server.CompleteHandshakeAsync(connection, discovery, deadline.Token);
        await connection.SendCommandAsync(Request("receipt-command"), deadline.Token);
        var command = await server.ReceiveAsync();
        var receiving = connection.ReceiveAsync(deadline.Token).AsTask();

        // When
        await server.SendAsync(Receipt("receipt-1", command.Id, "receipt-command"));
        var accepted = await receiving;
        var receivingDuplicate = connection.ReceiveAsync(deadline.Token).AsTask();
        await server.SendAsync(Receipt("receipt-2", command.Id, "receipt-command"));
        var duplicate = await Assert.ThrowsExceptionAsync<NativeProtocolError>(() => receivingDuplicate);

        // Then
        Assert.AreEqual(NativeMessageKind.Receipt, accepted.Kind);
        Assert.AreEqual("E_CORRELATION", duplicate.Code);
    }

    [TestMethod]
    public async Task ReceiveAsync_WhenReceiptFrameIsDuplicated_RefusesReplayWithStableCode()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await server.CompleteHandshakeAsync(connection, discovery, deadline.Token);
        await connection.SendCommandAsync(Request("duplicate-command"), deadline.Token);
        var command = await server.ReceiveAsync();
        var receipt = Receipt("same-receipt", command.Id, "duplicate-command");
        var receiving = connection.ReceiveAsync(deadline.Token).AsTask();
        await server.SendAsync(receipt);
        _ = await receiving;
        var receivingDuplicate = connection.ReceiveAsync(deadline.Token).AsTask();

        // When
        await server.SendAsync(receipt);
        var error = await Assert.ThrowsExceptionAsync<NativeProtocolError>(() => receivingDuplicate);

        // Then
        Assert.AreEqual("E_DUPLICATE_FRAME_ID", error.Code);
    }

    [DataTestMethod]
    [DataRow("unknown-frame", "receipt-command")]
    [DataRow("use-command-frame", "different-command")]
    public async Task ReceiveAsync_WhenReceiptCorrelationMismatches_RefusesWithStableCode(
        string replyMode,
        string receiptCommandId)
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await server.CompleteHandshakeAsync(connection, discovery, deadline.Token);
        await connection.SendCommandAsync(Request("receipt-command"), deadline.Token);
        var command = await server.ReceiveAsync();
        var reply = replyMode == "use-command-frame" ? command.Id : replyMode;
        var receiving = connection.ReceiveAsync(deadline.Token).AsTask();

        // When
        await server.SendAsync(Receipt("mismatched-receipt", reply, receiptCommandId));
        var error = await Assert.ThrowsExceptionAsync<NativeProtocolError>(() => receiving);

        // Then
        Assert.AreEqual("E_CORRELATION", error.Code);
    }

    [TestMethod]
    public async Task ReceiveAsync_WhenServerFrameCarriesUnsolicitedCorrelation_RefusesWithStableCode()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await server.CompleteHandshakeAsync(connection, discovery, deadline.Token);
        var receiving = connection.ReceiveAsync(deadline.Token).AsTask();
        var snapshot = new NativeEnvelope(
            NativeMessageKind.Snapshot,
            new NativeEnvelopeIdentity("snapshot-correlated", "client-unknown"),
            SnapshotBody());

        // When
        await server.SendAsync(snapshot);
        var error = await Assert.ThrowsExceptionAsync<NativeProtocolError>(() => receiving);

        // Then
        Assert.AreEqual("E_CORRELATION", error.Code);
    }

    [TestMethod]
    public async Task ReceiveAsync_WhenCorrelatedErrorExpiresCapability_ClearsAuthority()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await server.CompleteHandshakeAsync(connection, discovery, deadline.Token);
        await connection.SendCommandAsync(Request("expiring-command"), deadline.Token);
        var command = await server.ReceiveAsync();
        var receiving = connection.ReceiveAsync(deadline.Token).AsTask();
        var expired = new NativeEnvelope(
            NativeMessageKind.Error,
            new NativeEnvelopeIdentity("expired-error", command.Id),
            Object(
                ("code", new NativeJsonString("E_CAPABILITY_EXPIRED")),
                ("message", new NativeJsonString("bounded refusal")),
                ("retryable", new NativeJsonBoolean(false))));

        // When
        await server.SendAsync(expired);
        var refusal = await Assert.ThrowsExceptionAsync<NativeCommandRefusal>(() => receiving);

        // Then
        Assert.AreEqual("E_CAPABILITY_EXPIRED", refusal.Code);
        Assert.IsNull(connection.CurrentCapability);
    }

    [TestMethod]
    public async Task ReceiveAsync_WhenTransportReconnects_ClearsOldPendingCorrelation()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        var scheduled = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        ValueTask Schedule(TimeSpan _, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            scheduled.TrySetResult();
            return ValueTask.CompletedTask;
        }
        await using var connection = new NativeClientConnection(delayAsync: Schedule, jitter: () => 0.5);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await server.CompleteHandshakeAsync(connection, discovery, deadline.Token);
        await connection.SendCommandAsync(Request("before-disconnect"), deadline.Token);
        var oldCommand = await server.ReceiveAsync();
        discovery.Refresh(server.Port);
        var receiving = connection.ReceiveAsync(deadline.Token).AsTask();

        // When
        await server.DisconnectClientAsync();
        await scheduled.Task.WaitAsync(deadline.Token);
        var reconnectHello = await server.ReceiveAsync();
        await server.SendAsync(NativeHandshakeTests.Ready(reconnectHello.Id));
        _ = await server.ReceiveAsync();
        await server.SendAsync(Receipt("late-old-receipt", oldCommand.Id, "before-disconnect"));
        var error = await Assert.ThrowsExceptionAsync<NativeProtocolError>(() => receiving);

        // Then
        Assert.AreEqual("E_CORRELATION", error.Code);
    }

    private static NativeCommandRequest Request(string commandId) => new(
        new NativeCommandIdentity(commandId, 0),
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

    private static NativeJsonObject SnapshotBody() => Object(
        ("protocol_version", new NativeJsonInteger(1)),
        ("session_id", new NativeJsonString("native-app")),
        ("cursor", new NativeJsonInteger(0)),
        ("panels", new NativeJsonArray([])),
        ("conversation", new NativeJsonArray([])),
        ("composer", Object()),
        ("status", Object()),
        ("working_memory", Object()),
        ("approval_policy", Object()),
        ("terminals", new NativeJsonArray([])),
        ("instance_id", new NativeJsonString(TestDiscovery.InstanceId)),
        ("reset_reason", new NativeJsonString("initial")));

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));
}
