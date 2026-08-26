using System.Collections.Concurrent;
using System.Reflection;
using System.Runtime.ExceptionServices;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests;

public sealed partial class ShellCoordinatorConcurrencyTests
{
    private static NativeEnvelope Snapshot() => new(
        NativeMessageKind.Snapshot,
        "snapshot-1",
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("session_id", new NativeJsonString("session-1")),
            ("cursor", new NativeJsonInteger(4)),
            ("panels", new NativeJsonArray([])),
            ("conversation", new NativeJsonArray([])),
            ("composer", Object(("can_send", new NativeJsonBoolean(true)))),
            ("status", Object()),
            ("working_memory", Object()),
            ("approval_policy", Object()),
            ("terminals", new NativeJsonArray([])),
            ("instance_id", new NativeJsonString(InstanceId)),
            ("reset_reason", new NativeJsonString("initial"))));

    private static NativeEnvelope Event(long cursor, string commandId, string text) => new(
        NativeMessageKind.Event,
        $"event-{cursor}",
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("event_id", new NativeJsonString($"event-{cursor}")),
            ("session_id", new NativeJsonString("session-1")),
            ("cursor", new NativeJsonInteger(cursor)),
            ("type", new NativeJsonString("message.user")),
            ("timestamp", new NativeJsonString("2026-08-24T01:00:00+00:00")),
            ("actor_id", new NativeJsonString("user")),
            ("command_id", new NativeJsonString(commandId)),
            ("payload", Object(("text", new NativeJsonString(text))))));

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

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));

    private static string AnnouncementJson() => TestBridgeAnnouncement.Json();

    private sealed class Fixture : IAsyncDisposable
    {
        private Fixture(ControlledConnection connection, SynchronizationContext context,
            ShellPresentationModel model, ShellCoordinator coordinator) =>
            (Connection, Context, Model, Coordinator, Store) =
                (connection, context, model, coordinator, connection.Store);

        public ControlledConnection Connection { get; }
        public SynchronizationContext Context { get; }
        public ShellPresentationModel Model { get; }
        public ShellCoordinator Coordinator { get; }
        public NativeProjectionStore Store { get; }

        public void DrainPresentation()
        {
            if (Context is ConcurrentSynchronizationContext queued) queued.RunAll();
        }

        public static async Task<Fixture> CreateAsync(SynchronizationContext? suppliedContext = null)
        {
            var store = new NativeProjectionStore();
            var connection = new ControlledConnection(store);
            var context = suppliedContext ?? new ConcurrentSynchronizationContext();
            var model = new ShellPresentationModel(context);
            var coordinator = new ShellCoordinator(connection, store, model)
            {
                CommandIdFactory = () => "command-1",
            };
            await coordinator.ConnectAsync(AnnouncementJson(), "0.4.276", CancellationToken.None);
            store.ApplySnapshot(Snapshot(), new NativeReadyIdentity("session-1", InstanceId, "0.4.276"));
            if (context is ConcurrentSynchronizationContext queued) queued.RunAll();
            return new Fixture(connection, context, model, coordinator);
        }

        public ValueTask DisposeAsync() => Coordinator.DisposeAsync();
    }

    private sealed class ControlledConnection(NativeProjectionStore store) : INativeClientConnection
    {
        private readonly TaskCompletionSource<NativeEnvelope> _receipt =
            new(TaskCreationOptions.RunContinuationsAsynchronously);
        private int _authorityReadSignaled;

        public NativeProjectionStore Store { get; } = store;
        public TaskCompletionSource SendEntered { get; } =
            new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource? AuthorityRead { get; private set; }
        public TaskCompletionSource? ReleaseAuthority { get; private set; }
        public bool OwnsReceiveLoop => true;
        public NativeProjectionStore ProjectionStore => Store;
        public IReadOnlySet<string> AdvertisedCommands { get; } = new HashSet<string>(["chat.send"]);

        public void ArmAuthorityBarrier(
            TaskCompletionSource authorityRead,
            TaskCompletionSource releaseAuthority)
        {
            AuthorityRead = authorityRead;
            ReleaseAuthority = releaseAuthority;
            Volatile.Write(ref _authorityReadSignaled, 0);
        }

        public bool HasLiveCapability(DateTimeOffset now)
        {
            if (AuthorityRead is not null
                && Interlocked.Exchange(ref _authorityReadSignaled, 1) == 0)
            {
                AuthorityRead.TrySetResult();
                ReleaseAuthority!.Task.GetAwaiter().GetResult();
            }
            return true;
        }

        public Task ConnectAsync(BridgeAnnouncement announcement, string expectedProductVersion,
            CancellationToken cancellationToken) => Task.CompletedTask;

        public ValueTask<NativeEnvelope> SendCommandForResultAsync(
            NativeCommandRequest request, CancellationToken cancellationToken)
        {
            SendEntered.TrySetResult();
            return new ValueTask<NativeEnvelope>(_receipt.Task.WaitAsync(cancellationToken));
        }

        public void CompleteReceipt(NativeEnvelope receipt) => _receipt.TrySetResult(receipt);
        public ValueTask<NativeEnvelope> ReceiveAsync(CancellationToken cancellationToken) =>
            ValueTask.FromException<NativeEnvelope>(new NotSupportedException());
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

}
