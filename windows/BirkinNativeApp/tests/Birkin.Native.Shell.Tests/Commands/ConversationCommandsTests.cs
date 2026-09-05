using Birkin.Native.Protocol.Framing;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Commands;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class ConversationCommandsTests
{
    [TestMethod]
    public void Send_WhenDraftIsSubmitted_BuildsExactStableRequest()
    {
        // Given
        var context = new CommandRequestContext("chat-command-1", 41, "conversation");

        // When
        var request = ConversationCommands.Send(" exact draft \n", context);

        // Then
        Assert.AreEqual("chat-command-1", request.CommandId);
        Assert.AreEqual(41L, request.ExpectedCursor);
        Assert.AreEqual("conversation", request.ViewId);
        Assert.AreEqual("chat.send", request.CommandType);
        Assert.AreEqual(1, request.Payload.Count);
        Assert.AreEqual(" exact draft \n", ((NativeJsonString)request.Payload["text"]!).Value);
    }

    [TestMethod]
    public void Send_WhenFileIsSelected_AttachesExactValidatedReference()
    {
        var attachment = new ImportedFilePresentation(
            "import-1",
            "first-report.xlsx",
            "import-1.xlsx",
            new string('a', 64),
            1200);

        var request = ConversationCommands.Send(
            "inspect",
            new CommandRequestContext("chat-command-1", 41, "conversation"),
            [attachment]);

        var attachments = (NativeJsonArray)request.Payload["attachments"]!;
        var reference = (NativeJsonObject)attachments.Values.Single();
        Assert.AreEqual(2, request.Payload.Count);
        Assert.AreEqual("workspace_import", ((NativeJsonString)reference["kind"]!).Value);
        Assert.AreEqual("import-1", ((NativeJsonString)reference["import_id"]!).Value);
        Assert.AreEqual("first-report.xlsx", ((NativeJsonString)reference["display_name"]!).Value);
        Assert.AreEqual("import-1.xlsx", ((NativeJsonString)reference["jail_name"]!).Value);
        Assert.AreEqual(new string('a', 64), ((NativeJsonString)reference["sha256"]!).Value);
        Assert.AreEqual(1200L, ((NativeJsonInteger)reference["byte_count"]!).Value);
    }
}
