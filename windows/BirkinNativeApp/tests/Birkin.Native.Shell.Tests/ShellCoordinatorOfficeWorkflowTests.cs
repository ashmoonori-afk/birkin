using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class ShellCoordinatorOfficeWorkflowTests
{
    private const string InstanceId = "0123456789abcdef0123456789abcdef";

    [DataTestMethod]
    [DataRow("chat.send")]
    [DataRow("chat.interrupt")]
    [DataRow("file.import")]
    [DataRow("approval.answer")]
    [DataRow("office.compare")]
    public async Task Submit_WhenCommandIsUnadvertised_NeverWritesTransport(string commandType)
    {
        // Given
        var fixture = await Fixture.ConnectAsync(new HashSet<string>());

        // When
        var submitted = commandType switch
        {
            "chat.send" => await fixture.Coordinator.SendConversationAsync(CancellationToken.None),
            "chat.interrupt" => await fixture.Coordinator.InterruptConversationAsync(CancellationToken.None),
            "file.import" => await fixture.Coordinator.ImportAsync(new FileImportIntent(@"C:\input.xlsx"), CancellationToken.None),
            "approval.answer" => await fixture.Coordinator.AnswerApprovalAsync(new ApprovalAnswerIntent("approval-1", ApprovalDecision.Reject), CancellationToken.None),
            "office.compare" => await fixture.Coordinator.CompareOfficeDocumentsAsync(new OfficeCompareIntent("artifact-left", "artifact-right"), CancellationToken.None),
            _ => throw new AssertFailedException(),
        };

        // Then
        Assert.IsFalse(submitted);
        Assert.AreEqual(0, fixture.Connection.Sent.Count);
        await fixture.DisposeAsync();
    }

    [TestMethod]
    public async Task InterruptConversation_WhenCanonicalTurnIsInterruptible_SubmitsEmptyIntent()
    {
        var fixture = await Fixture.ConnectAsync(
            new HashSet<string>(["chat.interrupt"]),
            canInterrupt: true);
        fixture.Connection.Enqueue(Receipt("command-1", 5));

        var submitted = await fixture.Coordinator.InterruptConversationAsync(
            CancellationToken.None);
        fixture.Context.RunAll();

        Assert.IsTrue(submitted);
        var request = fixture.Connection.Sent.Single();
        Assert.AreEqual("chat.interrupt", request.CommandType);
        Assert.AreEqual(4L, request.ExpectedCursor);
        Assert.AreEqual(0, request.Payload.Count);
        await fixture.DisposeAsync();
    }

    [TestMethod]
    public async Task InterruptConversation_WhenProjectionDisallowsInterrupt_NeverWritesTransport()
    {
        var fixture = await Fixture.ConnectAsync(
            new HashSet<string>(["chat.interrupt"]));

        var submitted = await fixture.Coordinator.InterruptConversationAsync(
            CancellationToken.None);
        fixture.Context.RunAll();

        Assert.IsFalse(submitted);
        Assert.AreEqual(0, fixture.Connection.Sent.Count);
        await fixture.DisposeAsync();
    }

    [TestMethod]
    public async Task InterruptConversation_WhenCursorIsStale_RetriesOnceAtAuthorityCursor()
    {
        var fixture = await Fixture.ConnectAsync(
            new HashSet<string>(["chat.interrupt"]),
            canInterrupt: true);
        fixture.Connection.Enqueue(Stale("command-1", 9));
        fixture.Connection.Enqueue(Receipt("command-1", 10));

        var submitted = await fixture.Coordinator.InterruptConversationAsync(
            CancellationToken.None);
        fixture.Context.RunAll();

        Assert.IsTrue(submitted);
        Assert.AreEqual(2, fixture.Connection.Sent.Count);
        CollectionAssert.AreEqual(
            new long[] { 4, 9 },
            fixture.Connection.Sent.Select(request => request.ExpectedCursor).ToArray());
        Assert.IsTrue(fixture.Connection.Sent.All(request =>
            request.CommandId == "command-1"
            && request.CommandType == "chat.interrupt"));
        await fixture.DisposeAsync();
    }

    [TestMethod]
    public async Task ReportSaveCommands_WhenJobRequestAdvertised_EnableDraftOnly()
    {
        var commands = new HashSet<string>(["office.create", "office.convert", "office.job_request"]);
        var fixture = await Fixture.ConnectAsync(commands);
        Assert.IsTrue(fixture.Model.OfficeWorkflow.Availability.OfficeDraft.IsEnabled);
        fixture.Connection.Enqueue(Receipt("command-1", 5));

        var created = await fixture.Coordinator.CreateOfficeDocumentAsync(
            new OfficeCreateIntent("docx", new OfficeDocumentContent(["Report"]), "report.docx"),
            CancellationToken.None);
        var drafted = await fixture.Coordinator.DraftOfficeDocumentAsync(
            new OfficeDraftIntent(
                "Create the report",
                "docx",
                new OfficeDocumentContent(["Report", "Approved body"]),
                "Create a new report",
                "report.docx",
                false),
            CancellationToken.None);
        var converted = await fixture.Coordinator.ConvertOfficeDocumentAsync(
            new OfficeConvertIntent(
                new OfficeArtifact("artifact-1", "hash", "application/test", "file:///test", "private", "acl"),
                "txt",
                "output.txt",
                OfficeLossBudget.Zero),
            CancellationToken.None);

        Assert.IsFalse(created);
        Assert.IsTrue(drafted);
        Assert.IsFalse(converted);
        Assert.AreEqual(1, fixture.Connection.Sent.Count);
        Assert.AreEqual("office.job_request", fixture.Connection.Sent[0].CommandType);
        Assert.AreEqual("E_OFFICE_JOB_REQUEST_REQUIRED", fixture.Model.OfficeWorkflow.Availability.OfficeCreate.DisabledReason);
        Assert.AreEqual("E_OFFICE_JOB_REQUEST_REQUIRED", fixture.Model.OfficeWorkflow.Availability.OfficeConvert.DisabledReason);
        await fixture.DisposeAsync();
    }

    [TestMethod]
    public async Task SendConversation_WhenStale_PreservesDraftAndDoesNotReplay()
    {
        // Given
        var fixture = await Fixture.ConnectAsync(new HashSet<string>(["chat.send"]));
        fixture.Coordinator.SetConversationDraft(" exact draft \n");
        fixture.Context.RunAll();
        fixture.Connection.Enqueue(Stale("command-1", 9));

        // When
        var submitted = await fixture.Coordinator.SendConversationAsync(CancellationToken.None);
        fixture.Context.RunAll();

        // Then
        Assert.IsFalse(submitted);
        Assert.AreEqual(1, fixture.Connection.Sent.Count);
        Assert.AreEqual("command-1", fixture.Connection.Sent[0].CommandId);
        Assert.AreEqual(4L, fixture.Connection.Sent[0].ExpectedCursor);
        Assert.AreEqual(" exact draft \n", fixture.Model.OfficeWorkflow.Draft);
        Assert.AreEqual(9L, fixture.Model.OfficeWorkflow.CurrentCursor);
        await fixture.DisposeAsync();
    }

    [DataTestMethod]
    [DataRow("chat.send")]
    [DataRow("file.import")]
    [DataRow("approval.answer")]
    [DataRow("office.select")]
    [DataRow("office.open")]
    [DataRow("office.compare")]
    public async Task Submit_WhenReceiptAccepted_UsesHelloScopeWithoutFabricatingVisibleSuccess(string commandType)
    {
        // Given
        var fixture = await Fixture.ConnectAsync(new HashSet<string>([commandType]));
        fixture.Coordinator.SetConversationDraft("draft");
        fixture.Context.RunAll();
        fixture.Connection.Enqueue(Receipt("command-1", 5));

        // When
        var submitted = commandType switch
        {
            "chat.send" => await fixture.Coordinator.SendConversationAsync(CancellationToken.None),
            "file.import" => await fixture.Coordinator.ImportAsync(new FileImportIntent(@"C:\input.xlsx"), CancellationToken.None),
            "approval.answer" => await fixture.Coordinator.AnswerApprovalAsync(new ApprovalAnswerIntent("approval-1", ApprovalDecision.Approve), CancellationToken.None),
            "office.select" => await fixture.Coordinator.SelectOfficeDocumentAsync(new OfficeSelectIntent("artifact-1"), CancellationToken.None),
            "office.open" => await fixture.Coordinator.OpenOfficeDocumentAsync(new OfficeOpenIntent(new OfficeArtifact("artifact-1", "hash", "application/test", "file:///test", "private", "acl")), CancellationToken.None),
            "office.compare" => await fixture.Coordinator.CompareOfficeDocumentsAsync(new OfficeCompareIntent("artifact-left", "artifact-right"), CancellationToken.None),
            _ => throw new AssertFailedException(),
        };
        fixture.Context.RunAll();

        // Then
        Assert.IsTrue(submitted);
        var helloViewId = ((NativeJsonString)NativeHandshake.CreateHello("0.4.276", "secret", "hello-1").Body["view_id"]!).Value;
        Assert.AreEqual(helloViewId, fixture.Connection.Sent.Single().ViewId);
        Assert.AreEqual(0, fixture.Model.Workspace?.Conversation.Count);
        Assert.AreEqual(0, fixture.Model.Workspace?.Activity.Count);
        Assert.AreEqual(0, fixture.Model.Workspace?.Office.Count);
        Assert.AreEqual(WorkflowCommandState.AcceptedPendingProjection, fixture.Model.OfficeWorkflow.CommandState);
        var availability = fixture.Model.OfficeWorkflow.Availability;
        Assert.IsFalse(new[] { availability.ConversationSend, availability.FileImport, availability.ApprovalAnswer,
            availability.OfficeCreate, availability.OfficeSelect, availability.OfficeOpen, availability.OfficeCompare,
            availability.OfficeDraft, availability.OfficeConvert }.Any(item => item.IsEnabled));
        await fixture.DisposeAsync();
    }

    [TestMethod]
    public async Task SendConversation_WhenCanonicalEventsSurroundReceipt_AppliesBothWithoutOptimism()
    {
        // Given
        var fixture = await Fixture.ConnectAsync(new HashSet<string>(["chat.send"]));
        fixture.Coordinator.SetConversationDraft("draft");
        fixture.Context.RunAll();
        fixture.Connection.Enqueue(Event(5, "message.user", Object(("text", new NativeJsonString("before")))));
        fixture.Connection.Enqueue(Receipt("command-1", 5));

        // When
        var submitted = await fixture.Coordinator.SendConversationAsync(CancellationToken.None);
        fixture.Context.RunAll();
        Assert.AreEqual("before", fixture.Model.Workspace?.Conversation.Single().Text);
        fixture.Connection.Enqueue(Event(6, "message.assistant.completed", Object(("text", new NativeJsonString("after")))));
        await fixture.Coordinator.ReceiveCanonicalAsync(CancellationToken.None);
        fixture.Context.RunAll();

        // Then
        Assert.IsTrue(submitted);
        CollectionAssert.AreEqual(
            new[] { "before", "after" },
            fixture.Model.Workspace?.Conversation.Select(row => row.Text).ToArray());
        Assert.AreEqual(string.Empty, fixture.Model.OfficeWorkflow.Draft);
        await fixture.DisposeAsync();
    }

    [TestMethod]
    public async Task Import_WhenReceiptContainsJailedReference_ProjectsImportedFile()
    {
        var fixture = await Fixture.ConnectAsync(
            new HashSet<string>(["file.import"]));
        fixture.Connection.Enqueue(
            Receipt(
                "command-1",
                5,
                Object(
                    ("reference", Object(
                        ("kind", new NativeJsonString("workspace_import")),
                        ("import_id", new NativeJsonString("import-1")),
                        ("display_name", new NativeJsonString("first-report.xlsx")),
                        ("jail_name", new NativeJsonString("import-1.xlsx")),
                        ("sha256", new NativeJsonString(new string('a', 64))),
                        ("byte_count", new NativeJsonInteger(1200)))))));

        var submitted = await fixture.Coordinator.ImportAsync(
            new FileImportIntent(@"C:\input.xlsx"),
            CancellationToken.None);
        fixture.Context.RunAll();

        Assert.IsTrue(submitted);
        var imported = fixture.Model.OfficeWorkflow.Imports.Single();
        Assert.AreEqual("import-1", imported.ImportId);
        Assert.AreEqual("first-report.xlsx", imported.DisplayName);
        Assert.AreEqual(1200L, imported.ByteCount);
        await fixture.DisposeAsync();
    }

    [TestMethod]
    public async Task Import_WhenCanonicalEventPrecedesReceipt_ProjectsImportedFile()
    {
        var fixture = await Fixture.ConnectAsync(
            new HashSet<string>(["file.import"]));
        fixture.Connection.Enqueue(
            Event(
                5,
                "message.user",
                Object(("text", new NativeJsonString("import accepted")))));
        fixture.Connection.Enqueue(
            Receipt(
                "command-1",
                5,
                Object(
                    ("reference", Object(
                        ("kind", new NativeJsonString("workspace_import")),
                        ("import_id", new NativeJsonString("import-1")),
                        ("display_name", new NativeJsonString("first-report.xlsx")),
                        ("jail_name", new NativeJsonString("import-1.xlsx")),
                        ("sha256", new NativeJsonString(new string('a', 64))),
                        ("byte_count", new NativeJsonInteger(1200)))))));

        var submitted = await fixture.Coordinator.ImportAsync(
            new FileImportIntent(@"C:\input.xlsx"),
            CancellationToken.None);
        fixture.Context.RunAll();

        Assert.IsTrue(submitted);
        Assert.AreEqual(
            WorkflowCommandState.Idle,
            fixture.Model.OfficeWorkflow.CommandState);
        Assert.AreEqual(
            "first-report.xlsx",
            fixture.Model.OfficeWorkflow.Imports.Single().DisplayName);
        await fixture.DisposeAsync();
    }

    [TestMethod]
    public async Task Import_WhenReceiptReferenceIsMalformed_RefusesWithoutThrowing()
    {
        var fixture = await Fixture.ConnectAsync(
            new HashSet<string>(["file.import"]));
        fixture.Connection.Enqueue(
            Receipt(
                "command-1",
                5,
                Object(
                    ("reference", Object(
                        ("kind", new NativeJsonString("workspace_import")),
                        ("import_id", new NativeJsonString("import-1")),
                        ("display_name", new NativeJsonString("first-report.xlsx")),
                        ("jail_name", new NativeJsonString("import-1.xlsx")),
                        ("sha256", new NativeJsonString(new string('a', 63))),
                        ("byte_count", new NativeJsonInteger(1200)))))));

        var submitted = await fixture.Coordinator.ImportAsync(
            new FileImportIntent(@"C:\input.xlsx"),
            CancellationToken.None);
        fixture.Context.RunAll();

        Assert.IsFalse(submitted);
        Assert.AreEqual(
            WorkflowCommandState.Refused,
            fixture.Model.OfficeWorkflow.CommandState);
        Assert.AreEqual("E_BODY", fixture.Model.OfficeWorkflow.RefusalCode);
        Assert.AreEqual(0, fixture.Model.OfficeWorkflow.Imports.Count);
        Assert.IsTrue(fixture.Connection.IsCapabilityLive);
        await fixture.DisposeAsync();
    }

    [TestMethod]
    public async Task Conversation_WhenReceiptCarriesImportReference_DoesNotProjectChip()
    {
        var fixture = await Fixture.ConnectAsync(
            new HashSet<string>(["chat.send"]));
        fixture.Coordinator.SetConversationDraft("hello");
        fixture.Context.RunAll();
        fixture.Connection.Enqueue(
            Receipt(
                "command-1",
                5,
                Object(
                    ("reference", Object(
                        ("kind", new NativeJsonString("workspace_import")),
                        ("import_id", new NativeJsonString("import-1")),
                        ("display_name", new NativeJsonString("first-report.xlsx")),
                        ("jail_name", new NativeJsonString("import-1.xlsx")),
                        ("sha256", new NativeJsonString(new string('a', 64))),
                        ("byte_count", new NativeJsonInteger(1200)))))));

        var submitted = await fixture.Coordinator.SendConversationAsync(
            CancellationToken.None);
        fixture.Context.RunAll();

        Assert.IsTrue(submitted);
        Assert.AreEqual(0, fixture.Model.OfficeWorkflow.Imports.Count);
        await fixture.DisposeAsync();
    }

    [TestMethod]
    public async Task Submit_WhenAuthorityClears_DisablesAndPreservesDraft()
    {
        // Given
        var fixture = await Fixture.ConnectAsync(new HashSet<string>(["chat.send"]));
        fixture.Coordinator.SetConversationDraft("draft survives");
        fixture.Context.RunAll();
        fixture.Connection.IsCapabilityLive = false;
        fixture.Connection.AdvertisedCommands = new HashSet<string>();

        // When
        var submitted = await fixture.Coordinator.SendConversationAsync(CancellationToken.None);
        fixture.Context.RunAll();

        // Then
        Assert.IsFalse(submitted);
        Assert.AreEqual("draft survives", fixture.Model.OfficeWorkflow.Draft);
        Assert.AreEqual(WorkflowCommandState.Idle, fixture.Model.OfficeWorkflow.CommandState);
        Assert.AreEqual(0, fixture.Connection.Sent.Count);
        await fixture.DisposeAsync();
    }

    private static NativeCommandRefusal Stale(string commandId, long cursor) =>
        (NativeCommandRefusal)(Activator.CreateInstance(
            typeof(NativeCommandRefusal),
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic,
            binder: null,
            args: [
                "E_STALE_CURSOR",
                commandId,
                "cursor is stale",
                false,
                cursor,
            ],
            culture: null) ?? throw new AssertFailedException());

    private static NativeEnvelope Receipt(
        string commandId,
        long cursor,
        NativeJsonObject? result = null) => new(
        NativeMessageKind.Receipt,
        "receipt-1",
        ReceiptBody(commandId, cursor, result));

    private static NativeJsonObject ReceiptBody(
        string commandId,
        long cursor,
        NativeJsonObject? result)
    {
        List<(string Key, NativeJsonValue Value)> pairs =
        [
            ("protocol_version", new NativeJsonInteger(1)),
            ("command_id", new NativeJsonString(commandId)),
            ("session_id", new NativeJsonString("session-1")),
            ("actor_id", new NativeJsonString("windows:conversation")),
            ("accepted_cursor", new NativeJsonInteger(cursor)),
            ("state", new NativeJsonString("completed")),
            ("result_event_cursor", new NativeJsonInteger(cursor)),
            ("duplicate", new NativeJsonBoolean(false)),
            ("outcome", new NativeJsonString("accepted")),
        ];
        if (result is not null)
        {
            pairs.Add(("result", result));
        }
        return Object([.. pairs]);
    }

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

    private static NativeEnvelope Snapshot(bool canInterrupt) => new(
        NativeMessageKind.Snapshot,
        "snapshot-1",
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("session_id", new NativeJsonString("session-1")),
            ("cursor", new NativeJsonInteger(4)),
            ("panels", new NativeJsonArray([Object(("key", new NativeJsonString("activity_logs")), ("items", new NativeJsonArray([])))])),
            ("conversation", new NativeJsonArray([])),
            ("composer", Object(
                ("can_send", new NativeJsonBoolean(true)),
                ("can_interrupt", new NativeJsonBoolean(canInterrupt)))),
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

        public static async Task<Fixture> ConnectAsync(
            IReadOnlySet<string> commands,
            bool canInterrupt = false)
        {
            var connection = new TestConnection(commands);
            connection.Enqueue(Snapshot(canInterrupt));
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
