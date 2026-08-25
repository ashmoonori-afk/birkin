using Birkin.Native.Protocol.Framing;
using Birkin.Native.Shell.Commands;
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
}
