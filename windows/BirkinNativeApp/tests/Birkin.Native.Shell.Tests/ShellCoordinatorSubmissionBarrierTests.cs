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
    [TestMethod]
    public async Task PendingTerminalSubmission_ExcludesConcurrentConversationAndOfficeCommandsByExactBarrier()
    {
        var store = new NativeProjectionStore();
        var connection = new SerializedSubmissionConnection(store);
        var context = new ConcurrentSynchronizationContext();
        var model = new ShellPresentationModel(context);
        await using var coordinator = new ShellCoordinator(connection, store, model)
        {
            CommandIdFactory = () => "terminal-command-73",
        };
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        await coordinator.ConnectAsync(AnnouncementJson(), "0.4.276", deadline.Token);
        store.ApplySnapshot(Snapshot(), new NativeReadyIdentity("session-1", InstanceId, "0.4.276"));
        context.RunAll();
        coordinator.SetConversationDraft("conversation must remain queued");

        Assert.IsNotNull(typeof(ShellCoordinator).GetMethod(
            "CreateTerminalAsync",
            BindingFlags.Instance | BindingFlags.Public,
            binder: null,
            types: [typeof(string), typeof(CancellationToken)],
            modifiers: null),
            "ShellCoordinator must provide terminal creation before the exact submission barrier can run");
        var terminal = InvokeTerminalCreateAsync(
            coordinator,
            @"C:\workspace\serialized-91",
            deadline.Token);
        await connection.SendEntered.Task.WaitAsync(deadline.Token);
        context.RunAll();
        var terminalWorkflow = model.GetType().GetProperty("TerminalWorkflow")?.GetValue(model);
        Assert.IsNotNull(terminalWorkflow, "pending terminal submission must be publicly observable without its lease");
        Assert.AreEqual(
            "PendingReceipt",
            terminalWorkflow.GetType().GetProperty("CommandState")?.GetValue(terminalWorkflow)?.ToString());
        var conversation = coordinator.SendConversationAsync(deadline.Token);
        var office = coordinator.CreateOfficeDocumentAsync(
            new OfficeCreateIntent(
                "docx",
                new OfficeDocumentContent(["Office must remain queued"]),
                "serialized-47.docx"),
            deadline.Token);

        Assert.IsFalse(await conversation);
        Assert.IsFalse(await office);
        Assert.AreEqual(1, connection.Sent.Count);
        Assert.AreEqual("terminal.create", connection.Sent.Single().CommandType);
        connection.CompleteReceipt(ReceiptWithResult(
            "terminal-command-73",
            5,
            Object(
                ("terminal_id", new NativeJsonString("terminal-510")),
                ("lease", new NativeJsonString("transient-lease-204")))));
        Assert.IsTrue(await terminal);
    }

    private static async Task<bool> InvokeTerminalCreateAsync(
        ShellCoordinator coordinator,
        string cwd,
        CancellationToken cancellationToken)
    {
        var method = typeof(ShellCoordinator).GetMethod(
            "CreateTerminalAsync",
            BindingFlags.Instance | BindingFlags.Public,
            binder: null,
            types: [typeof(string), typeof(CancellationToken)],
            modifiers: null);
        Assert.IsNotNull(method, "ShellCoordinator must provide typed terminal creation");
        try
        {
            var result = method.Invoke(coordinator, [cwd, cancellationToken]);
            Assert.IsInstanceOfType<Task<bool>>(result);
            return await (Task<bool>)result;
        }
        catch (TargetInvocationException error) when (error.InnerException is not null)
        {
            ExceptionDispatchInfo.Capture(error.InnerException).Throw();
            throw;
        }
    }

    private static NativeEnvelope ReceiptWithResult(
        string commandId,
        long cursor,
        NativeJsonObject result) => new(
        NativeMessageKind.Receipt,
        "receipt-terminal-29",
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("command_id", new NativeJsonString(commandId)),
            ("session_id", new NativeJsonString("session-1")),
            ("actor_id", new NativeJsonString("windows:terminal")),
            ("accepted_cursor", new NativeJsonInteger(cursor)),
            ("state", new NativeJsonString("completed")),
            ("result_event_cursor", new NativeJsonInteger(cursor)),
            ("duplicate", new NativeJsonBoolean(false)),
            ("outcome", new NativeJsonString("accepted")),
            ("result", result)));

    private sealed class SerializedSubmissionConnection(NativeProjectionStore store) : INativeClientConnection
    {
        private readonly TaskCompletionSource<NativeEnvelope> _receipt =
            new(TaskCreationOptions.RunContinuationsAsynchronously);

        public TaskCompletionSource SendEntered { get; } =
            new(TaskCreationOptions.RunContinuationsAsynchronously);
        public List<NativeCommandRequest> Sent { get; } = [];
        public bool OwnsReceiveLoop => true;
        public NativeProjectionStore ProjectionStore { get; } = store;
        public IReadOnlySet<string> AdvertisedCommands { get; } = new HashSet<string>(
            ["terminal.create", "chat.send", "office.create"]);
        public bool HasLiveCapability(DateTimeOffset now) => true;
        public Task ConnectAsync(BridgeAnnouncement announcement, string expectedProductVersion,
            CancellationToken cancellationToken) => Task.CompletedTask;
        public ValueTask<NativeEnvelope> SendCommandForResultAsync(
            NativeCommandRequest request,
            CancellationToken cancellationToken)
        {
            Sent.Add(request);
            SendEntered.TrySetResult();
            return new ValueTask<NativeEnvelope>(_receipt.Task.WaitAsync(cancellationToken));
        }
        public void CompleteReceipt(NativeEnvelope receipt) => _receipt.TrySetResult(receipt);
        public ValueTask<NativeEnvelope> ReceiveAsync(CancellationToken cancellationToken) =>
            ValueTask.FromException<NativeEnvelope>(new NotSupportedException());
        public ValueTask DisposeAsync()
        {
            _receipt.TrySetCanceled();
            return ValueTask.CompletedTask;
        }
    }

}
