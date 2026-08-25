using System.Collections.Concurrent;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests;

[TestClass]
public sealed class ShellCoordinatorConcurrencyTests
{
    private const string InstanceId = "0123456789abcdef0123456789abcdef";

    [TestMethod]
    public async Task ConcurrentDraftEditAndBackgroundConnectionTransition_PreserveBothChanges()
    {
        var authorityRead = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var releaseAuthority = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var connection = new ControlledConnection(new NativeProjectionStore());
        connection.ArmAuthorityBarrier(authorityRead, releaseAuthority);
        var context = new ConcurrentSynchronizationContext();
        var model = new ShellPresentationModel(context);
        await using var coordinator = new ShellCoordinator(connection, connection.Store, model);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));

        var connecting = Task.Run(() => coordinator.ConnectAsync(
            AnnouncementJson(), "0.4.276", deadline.Token), deadline.Token);
        await authorityRead.Task.WaitAsync(deadline.Token);
        coordinator.SetConversationDraft("draft written on UI thread");
        releaseAuthority.TrySetResult();
        await connecting;
        context.RunAll();

        Assert.AreEqual(ConnectionState.Subscribing, model.Connection.State);
        Assert.AreEqual("draft written on UI thread", model.OfficeWorkflow.Draft);
    }

    [TestMethod]
    public async Task CanonicalProjectionThenAuthorityRevocationWhileReceiptPending_LeavesMutationsDisabled()
    {
        await using var fixture = await Fixture.CreateAsync();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        fixture.Coordinator.SetConversationDraft("submitted draft");
        var submission = fixture.Coordinator.SendConversationAsync(deadline.Token);
        await fixture.Connection.SendEntered.Task.WaitAsync(deadline.Token);

        var authorityRead = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var releaseAuthority = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        fixture.Connection.ArmAuthorityBarrier(authorityRead, releaseAuthority);
        var canonical = Task.Run(
            () => fixture.Store.ApplyEvent(Event(5, "command-1", "projected")),
            deadline.Token);
        await authorityRead.Task.WaitAsync(deadline.Token);
        await Task.Run(fixture.Store.MarkMutationAuthorityUnavailable, deadline.Token);
        releaseAuthority.TrySetResult();
        await canonical;
        fixture.Connection.CompleteReceipt(Receipt("command-1", 5));
        Assert.IsTrue(await submission);
        fixture.DrainPresentation();

        Assert.AreEqual(WorkflowCommandState.Idle, fixture.Model.OfficeWorkflow.CommandState);
        Assert.IsFalse(fixture.Model.OfficeWorkflow.Availability.ConversationSend.IsEnabled);
        Assert.IsNotNull(fixture.Model.OfficeWorkflow.Availability.ConversationSend.DisabledReason);
    }

    [TestMethod]
    public async Task ReceiptAndCanonicalEventForSubmittedDraft_DoNotOverwriteNewerDraft()
    {
        await using var fixture = await Fixture.CreateAsync();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        fixture.Coordinator.SetConversationDraft("submitted draft");
        var submission = fixture.Coordinator.SendConversationAsync(deadline.Token);
        await fixture.Connection.SendEntered.Task.WaitAsync(deadline.Token);

        fixture.Coordinator.SetConversationDraft("newer draft");
        fixture.Connection.CompleteReceipt(Receipt("command-1", 5));
        Assert.IsTrue(await submission);
        fixture.Store.ApplyEvent(Event(5, "command-1", "projected"));
        fixture.DrainPresentation();

        Assert.AreEqual("newer draft", fixture.Model.OfficeWorkflow.Draft);
        Assert.AreEqual(WorkflowCommandState.Idle, fixture.Model.OfficeWorkflow.CommandState);
    }

    [TestMethod]
    public async Task ReentrantPresenter_CanMutateCoordinatorWithoutWaitingForStateLock()
    {
        ShellCoordinator? coordinator = null;
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var context = new ReentrantSynchronizationContext(() =>
            Task.Run(() => coordinator!.SetConversationDraft("reentrant"), deadline.Token));
        var connection = new ControlledConnection(new NativeProjectionStore());
        var model = new ShellPresentationModel(context);
        await using (coordinator = new ShellCoordinator(connection, connection.Store, model))
        {
            coordinator.SetConversationDraft("outer");
        }

        Assert.IsTrue(context.ReentrantMutationCompleted);
    }

    [TestMethod]
    public async Task CanonicalPresentationSnapshot_ContainsMatchingProjectionAndWorkflowState()
    {
        var context = new ImmediateSynchronizationContext();
        await using var fixture = await Fixture.CreateAsync(context);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        fixture.Coordinator.SetConversationDraft("submitted draft");
        var submission = fixture.Coordinator.SendConversationAsync(deadline.Token);
        await fixture.Connection.SendEntered.Task.WaitAsync(deadline.Token);
        fixture.Connection.CompleteReceipt(Receipt("command-1", 5));
        Assert.IsTrue(await submission);

        OfficeWorkflowPresentation? workflowSeenWithProjection = null;
        fixture.Model.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(ShellPresentationModel.Workspace)
                && fixture.Model.Workspace?.Cursor == 5)
            {
                workflowSeenWithProjection = fixture.Model.OfficeWorkflow;
            }
        };
        fixture.Store.ApplyEvent(Event(5, "command-1", "projected"));

        Assert.IsNotNull(workflowSeenWithProjection);
        Assert.AreEqual(WorkflowCommandState.Idle, workflowSeenWithProjection.CommandState);
        Assert.IsTrue(workflowSeenWithProjection.Availability.ConversationSend.IsEnabled);
    }

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

    private sealed class ConcurrentSynchronizationContext : SynchronizationContext
    {
        private readonly ConcurrentQueue<(SendOrPostCallback Callback, object? State)> _work = new();
        public override void Post(SendOrPostCallback d, object? state) => _work.Enqueue((d, state));
        public void RunAll()
        {
            while (_work.TryDequeue(out var work)) work.Callback(work.State);
        }
    }

    private sealed class ImmediateSynchronizationContext : SynchronizationContext
    {
        public override void Post(SendOrPostCallback d, object? state) => d(state);
    }

    private sealed class ReentrantSynchronizationContext(Func<Task> mutation) : SynchronizationContext
    {
        private int _reentered;
        public bool ReentrantMutationCompleted { get; private set; }

        public override void Post(SendOrPostCallback d, object? state)
        {
            if (Interlocked.Exchange(ref _reentered, 1) == 0)
            {
                ReentrantMutationCompleted = mutation().Wait(TimeSpan.FromSeconds(2));
            }
            d(state);
        }
    }
}
