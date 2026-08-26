using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests;

public sealed partial class ShellCoordinatorOfficeWorkflowTests
{
    private static NativeCommandRefusal Stale(string commandId, long cursor) =>
        (NativeCommandRefusal)(Activator.CreateInstance(
            typeof(NativeCommandRefusal),
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic,
            binder: null,
            args: ["E_STALE_CURSOR", "stale cursor refusal", commandId, cursor, null],
            culture: null) ?? throw new AssertFailedException());

    private static NativeEnvelope Receipt(string commandId, long cursor) => new(
        NativeMessageKind.Receipt,
        "receipt-1",
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("command_id", new NativeJsonString(commandId)),
            ("session_id", new NativeJsonString("session-1")),
            ("actor_id", new NativeJsonString("windows:conversation")),
            ("accepted_cursor", new NativeJsonInteger(cursor)),
            ("state", new NativeJsonString("completed")),
            ("result_event_cursor", new NativeJsonInteger(cursor)),
            ("duplicate", new NativeJsonBoolean(false)),
            ("outcome", new NativeJsonString("accepted"))));

    private static NativeEnvelope Event(long cursor, string type, NativeJsonObject payload) => new(
        NativeMessageKind.Event,
        $"event-{cursor}",
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("event_id", new NativeJsonString($"event-{cursor}")),
            ("session_id", new NativeJsonString("session-1")),
            ("cursor", new NativeJsonInteger(cursor)),
            ("type", new NativeJsonString(type)),
            ("timestamp", new NativeJsonString("2026-08-24T01:00:00+00:00")),
            ("actor_id", new NativeJsonString("user")),
            ("command_id", new NativeJsonString("command-1")),
            ("payload", payload)));

    private static NativeEnvelope Snapshot() => new(
        NativeMessageKind.Snapshot,
        "snapshot-1",
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("session_id", new NativeJsonString("session-1")),
            ("cursor", new NativeJsonInteger(4)),
            ("panels", new NativeJsonArray([Object(("key", new NativeJsonString("activity_logs")), ("items", new NativeJsonArray([])))])),
            ("conversation", new NativeJsonArray([])),
            ("composer", Object(("can_send", new NativeJsonBoolean(true)))),
            ("status", Object()),
            ("working_memory", Object()),
            ("approval_policy", Object()),
            ("terminals", new NativeJsonArray([])),
            ("instance_id", new NativeJsonString(InstanceId)),
            ("reset_reason", new NativeJsonString("initial"))));

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));

    private sealed class Fixture : IAsyncDisposable
    {
        private Fixture(TestConnection connection, DeterministicSynchronizationContext context,
            ShellPresentationModel model, ShellCoordinator coordinator) =>
            (Connection, Context, Model, Coordinator) = (connection, context, model, coordinator);

        public TestConnection Connection { get; }
        public DeterministicSynchronizationContext Context { get; }
        public ShellPresentationModel Model { get; }
        public ShellCoordinator Coordinator { get; }

        public static async Task<Fixture> ConnectAsync(IReadOnlySet<string> commands)
        {
            var connection = new TestConnection(commands);
            connection.Enqueue(Snapshot());
            var context = new DeterministicSynchronizationContext();
            var model = new ShellPresentationModel(context);
            var coordinator = new ShellCoordinator(connection, new NativeProjectionStore(), model)
            {
                CommandIdFactory = () => "command-1",
            };
            await coordinator.ConnectAsync(
                TestBridgeAnnouncement.Json(),
                "0.4.276",
                CancellationToken.None);
            context.RunAll();
            return new Fixture(connection, context, model, coordinator);
        }

        public ValueTask DisposeAsync() => Coordinator.DisposeAsync();
    }

    private abstract record Received;
    private sealed record ReceivedEnvelope(NativeEnvelope Envelope) : Received;
    private sealed record ReceivedRefusal(NativeCommandRefusal Refusal) : Received;

    private sealed class TestConnection(IReadOnlySet<string> commands) : INativeClientConnection
    {
        private readonly Queue<Received> _received = new();
        public List<NativeCommandRequest> Sent { get; } = [];
        public bool IsCapabilityLive { get; set; } = true;
        public IReadOnlySet<string> AdvertisedCommands { get; set; } = commands;

        public bool HasLiveCapability(DateTimeOffset now) => IsCapabilityLive;

        public void Enqueue(NativeEnvelope envelope) => _received.Enqueue(new ReceivedEnvelope(envelope));
        public void Enqueue(NativeCommandRefusal refusal) => _received.Enqueue(new ReceivedRefusal(refusal));
        public Task ConnectAsync(BridgeAnnouncement announcement, string expectedProductVersion, CancellationToken cancellationToken) => Task.CompletedTask;
        public ValueTask SendCommandAsync(NativeCommandRequest request, CancellationToken cancellationToken)
        {
            Sent.Add(request);
            return ValueTask.CompletedTask;
        }
        public ValueTask<NativeEnvelope> ReceiveAsync(CancellationToken cancellationToken)
        {
            return _received.Dequeue() switch
            {
                ReceivedEnvelope frame => ValueTask.FromResult(frame.Envelope),
                ReceivedRefusal error => ValueTask.FromException<NativeEnvelope>(error.Refusal),
                _ => throw new AssertFailedException(),
            };
        }
        public ValueTask DisposeAsync()
        {
            IsCapabilityLive = false;
            AdvertisedCommands = new HashSet<string>();
            return ValueTask.CompletedTask;
        }
    }

    public sealed class DeterministicSynchronizationContext : SynchronizationContext
    {
        private readonly Queue<(SendOrPostCallback Callback, object? State)> _work = new();
        public override void Post(SendOrPostCallback d, object? state) => _work.Enqueue((d, state));
        public void RunAll()
        {
            while (_work.TryDequeue(out var work)) work.Callback(work.State);
        }
    }
}
