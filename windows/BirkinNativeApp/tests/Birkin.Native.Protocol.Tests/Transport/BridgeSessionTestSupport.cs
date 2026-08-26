using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Tests.Messaging;
using Birkin.Native.Protocol.Tests.Support;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Transport;

public sealed partial class BridgeSessionTests
{
    private static async Task ConnectAndSnapshotAsync(
        LoopbackServerHarness server,
        TestDiscovery discovery,
        BridgeSession session,
        CancellationToken cancellationToken)
    {
        var connecting = session.ConnectAsync(discovery.Announcement, TestDiscovery.Version, cancellationToken);
        var hello = await server.ReceiveAsync();
        await server.SendAsync(Ready(hello.Id));
        _ = await server.ReceiveAsync();
        await server.SendAsync(Snapshot());
        await connecting;
    }

    private static int ActiveReceiveCount(BridgeSession session)
    {
        var field = typeof(BridgeSession).GetField(
            "_activeReceives",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("BridgeSession active receive counter is unavailable.");
        return (int)(field.GetValue(session)
            ?? throw new InvalidOperationException("BridgeSession active receive counter is null."));
    }

    private static async Task<Exception> CaptureExceptionAsync(Task task)
    {
        try
        {
            await task;
        }
        catch (Exception error)
        {
            return error;
        }

        Assert.Fail("Expected the task to fault.");
        throw new InvalidOperationException("Assert.Fail unexpectedly returned.");
    }

    private static NativeEnvelope Ready(string reply)
    {
        var ready = NativeHandshakeTests.Ready(reply);
        return new NativeEnvelope(
            ready.Kind,
            new NativeEnvelopeIdentity(ready.Id, ready.InReplyTo),
            new NativeJsonObject(ready.Body.Pairs.Select(pair => pair.Key == "capability"
                ? new KeyValuePair<string, NativeJsonValue>(pair.Key, Object(
                    ("token", new NativeJsonString("capability-token")),
                    ("expires_at", new NativeJsonString("2099-08-24T02:00:00+00:00")),
                    ("hard_expires_at", new NativeJsonString("2099-08-24T08:00:00+00:00"))))
                : pair)));
    }

    private static NativeCommandRequest Request(string commandId) => new(
        new NativeCommandIdentity(commandId, 0),
        new NativeCommandIntent("chat.send", Object(("text", new NativeJsonString("hello")))),
        "conversation");

    private static NativeEnvelope Snapshot(string id = "snapshot-1", long cursor = 0) => new(
        NativeMessageKind.Snapshot,
        id,
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("session_id", new NativeJsonString("native-app")),
            ("cursor", new NativeJsonInteger(cursor)),
            ("panels", new NativeJsonArray([])),
            ("conversation", new NativeJsonArray([])),
            ("composer", Object(("can_send", new NativeJsonBoolean(true)))),
            ("status", Object()),
            ("working_memory", Object()),
            ("approval_policy", Object()),
            ("terminals", new NativeJsonArray([])),
            ("instance_id", new NativeJsonString(TestDiscovery.InstanceId)),
            ("reset_reason", new NativeJsonString("initial"))));

    private static NativeEnvelope Event(string id, long cursor, string commandId) => new(
        NativeMessageKind.Event,
        id,
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("event_id", new NativeJsonString(id)),
            ("session_id", new NativeJsonString("native-app")),
            ("actor_id", new NativeJsonString("windows:test")),
            ("cursor", new NativeJsonInteger(cursor)),
            ("type", new NativeJsonString("command.completed")),
            ("timestamp", new NativeJsonString("2026-08-24T01:00:00+00:00")),
            ("command_id", new NativeJsonString(commandId)),
            ("payload", Object(("outcome", new NativeJsonString("accepted"))))));

    private static NativeEnvelope Stale(string id, string reply, long currentCursor) => new(
        NativeMessageKind.Error,
        new NativeEnvelopeIdentity(id, reply),
        Object(
            ("code", new NativeJsonString("E_STALE_CURSOR")),
            ("message", new NativeJsonString($"stale cursor; current cursor is {currentCursor}")),
            ("retryable", new NativeJsonBoolean(false)),
            ("current_cursor", new NativeJsonInteger(currentCursor))));

    private static NativeEnvelope Surface(NativeMessageKind kind, long revision) => new(
        kind,
        $"surface-{revision}",
        Object(
            ("surface", new NativeJsonString("browser_aside")),
            ("revision", new NativeJsonInteger(revision)),
            ("payload", Object())));

    private static NativeEnvelope Receipt(string id, string reply, string commandId) => new(
        NativeMessageKind.Receipt,
        new NativeEnvelopeIdentity(id, reply),
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("command_id", new NativeJsonString(commandId)),
            ("session_id", new NativeJsonString("native-app")),
            ("actor_id", new NativeJsonString("windows:test")),
            ("accepted_cursor", new NativeJsonInteger(1)),
            ("state", new NativeJsonString("completed")),
            ("result_event_cursor", new NativeJsonInteger(1)),
            ("duplicate", new NativeJsonBoolean(false)),
            ("outcome", new NativeJsonString("accepted"))));

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));

    private static string String(NativeJsonObject body, string key) =>
        ((NativeJsonString)body[key]!).Value;

    private sealed class ImmediateSynchronizationContext : SynchronizationContext
    {
        public override void Post(SendOrPostCallback callback, object? state) => callback(state);
    }
}
