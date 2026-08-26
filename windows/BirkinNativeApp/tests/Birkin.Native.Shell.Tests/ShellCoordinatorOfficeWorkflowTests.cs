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
public sealed partial class ShellCoordinatorOfficeWorkflowTests
{
    private const string InstanceId = "0123456789abcdef0123456789abcdef";

    [DataTestMethod]
    [DataRow("chat.send")]
    [DataRow("file.import")]
    [DataRow("approval.answer")]
    [DataRow("office.create")]
    [DataRow("office.compare")]
    [DataRow("office.draft")]
    public async Task Submit_WhenCommandIsUnadvertised_NeverWritesTransport(string commandType)
    {
        // Given
        var fixture = await Fixture.ConnectAsync(new HashSet<string>());

        // When
        var submitted = commandType switch
        {
            "chat.send" => await fixture.Coordinator.SendConversationAsync(CancellationToken.None),
            "file.import" => await fixture.Coordinator.ImportAsync(new FileImportIntent(@"C:\input.xlsx"), CancellationToken.None),
            "approval.answer" => await fixture.Coordinator.AnswerApprovalAsync(new ApprovalAnswerIntent("approval-1", ApprovalDecision.Reject), CancellationToken.None),
            "office.create" => await fixture.Coordinator.CreateOfficeDocumentAsync(new OfficeCreateIntent("docx", new OfficeDocumentContent(["Report"]), "report.docx"), CancellationToken.None),
            "office.compare" => await fixture.Coordinator.CompareOfficeDocumentsAsync(new OfficeCompareIntent("artifact-left", "artifact-right"), CancellationToken.None),
            "office.draft" => await fixture.Coordinator.DraftOfficeDocumentAsync(new OfficeDraftIntent("artifact-template", "diff-1", "report.docx"), CancellationToken.None),
            _ => throw new AssertFailedException(),
        };

        // Then
        Assert.IsFalse(submitted);
        Assert.AreEqual(0, fixture.Connection.Sent.Count);
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
    [DataRow("office.create")]
    [DataRow("office.select")]
    [DataRow("office.open")]
    [DataRow("office.compare")]
    [DataRow("office.draft")]
    [DataRow("office.convert")]
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
            "office.create" => await fixture.Coordinator.CreateOfficeDocumentAsync(new OfficeCreateIntent("docx", new OfficeDocumentContent(["Report"]), "report.docx"), CancellationToken.None),
            "office.select" => await fixture.Coordinator.SelectOfficeDocumentAsync(new OfficeSelectIntent("artifact-1"), CancellationToken.None),
            "office.open" => await fixture.Coordinator.OpenOfficeDocumentAsync(new OfficeOpenIntent(new OfficeArtifact("artifact-1", "hash", "application/test", "file:///test", "private", "acl")), CancellationToken.None),
            "office.compare" => await fixture.Coordinator.CompareOfficeDocumentsAsync(new OfficeCompareIntent("artifact-left", "artifact-right"), CancellationToken.None),
            "office.draft" => await fixture.Coordinator.DraftOfficeDocumentAsync(new OfficeDraftIntent("artifact-template", "diff-1", "report.docx"), CancellationToken.None),
            "office.convert" => await fixture.Coordinator.ConvertOfficeDocumentAsync(new OfficeConvertIntent(new OfficeArtifact("artifact-1", "hash", "application/test", "file:///test", "private", "acl"), "txt", "output.txt", OfficeLossBudget.Zero), CancellationToken.None),
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

}
