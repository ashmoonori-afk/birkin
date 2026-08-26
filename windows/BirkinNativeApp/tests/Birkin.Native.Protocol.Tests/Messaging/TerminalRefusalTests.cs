using System.Reflection;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Tests.Support;
using Birkin.Native.Protocol.Transport;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Messaging;

[TestClass]
public sealed class TerminalRefusalTests
{
    [TestMethod]
    public async Task ReceiveAsync_WhenTerminalApprovalIsRequired_ExtractsOnlyTypedApprovalId()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await server.CompleteHandshakeAsync(connection, discovery, deadline.Token);
        await connection.SendCommandAsync(Request("terminal-create-73"), deadline.Token);
        var command = await server.ReceiveAsync();
        var receiving = connection.ReceiveAsync(deadline.Token).AsTask();

        // When
        await server.SendAsync(Refusal(
            "terminal-approval-error-91",
            command.Id,
            "E_TERMINAL_APPROVAL_REQUIRED",
            "approval-terminal-8642"));
        var refusal = await Assert.ThrowsExceptionAsync<NativeCommandRefusal>(() => receiving);

        // Then
        Assert.AreEqual("E_TERMINAL_APPROVAL_REQUIRED", refusal.Code);
        Assert.AreEqual("terminal-create-73", refusal.CommandId);
        Assert.AreEqual("approval-terminal-8642", ApprovalId(refusal));
        Assert.IsNull(refusal.CurrentCursor);
        Assert.IsNull(typeof(NativeCommandRefusal).GetProperty("Body", BindingFlags.Instance | BindingFlags.Public));
        Assert.IsNull(typeof(NativeCommandRefusal).GetProperty("Payload", BindingFlags.Instance | BindingFlags.Public));
        Assert.IsNull(typeof(NativeCommandRefusal).GetProperty("Result", BindingFlags.Instance | BindingFlags.Public));
    }

    [TestMethod]
    public async Task ReceiveAsync_WhenNonApprovalRefusalCarriesApprovalId_DoesNotExposeIt()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = TestDiscovery.Create(server.Port);
        await using var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await server.CompleteHandshakeAsync(connection, discovery, deadline.Token);
        await connection.SendCommandAsync(Request("terminal-close-47"), deadline.Token);
        var command = await server.ReceiveAsync();
        var receiving = connection.ReceiveAsync(deadline.Token).AsTask();

        // When
        await server.SendAsync(Refusal(
            "terminal-close-error-29",
            command.Id,
            "E_TERMINAL_SIGNAL_REJECTED",
            "must-not-be-exposed-510"));
        var refusal = await Assert.ThrowsExceptionAsync<NativeCommandRefusal>(() => receiving);

        // Then
        Assert.AreEqual("E_TERMINAL_SIGNAL_REJECTED", refusal.Code);
        Assert.IsNull(ApprovalId(refusal));
    }

    private static NativeCommandRequest Request(string commandId) => new(
        new NativeCommandIdentity(commandId, 37),
        new NativeCommandIntent(
            "terminal.create",
            Object(
                ("cwd", new NativeJsonString("C:/workspace/non-default-73")),
                ("approval_id", new NativeJsonString("approval-request-204")))),
        "terminal-region-19");

    private static NativeEnvelope Refusal(
        string id,
        string reply,
        string code,
        string approvalId) => new(
            NativeMessageKind.Error,
            new NativeEnvelopeIdentity(id, reply),
            Object(
                ("code", new NativeJsonString(code)),
                ("message", new NativeJsonString("bounded terminal guidance")),
                ("retryable", new NativeJsonBoolean(false)),
                ("approval_id", new NativeJsonString(approvalId))));

    private static string? ApprovalId(NativeCommandRefusal refusal)
    {
        var property = typeof(NativeCommandRefusal).GetProperty(
            "ApprovalId",
            BindingFlags.Instance | BindingFlags.Public);
        Assert.IsNotNull(property, "NativeCommandRefusal must expose a typed ApprovalId property");
        Assert.AreEqual(typeof(string), property.PropertyType);
        return (string?)property.GetValue(refusal);
    }

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));
}
