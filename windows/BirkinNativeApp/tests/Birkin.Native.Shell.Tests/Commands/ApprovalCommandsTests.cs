using Birkin.Native.Protocol.Framing;
using Birkin.Native.Shell.Commands;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Commands;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class ApprovalCommandsTests
{
    [TestMethod]
    public void Answer_WhenExplicitDecisionGiven_BuildsExactPythonPayload()
    {
        // Given
        var context = new CommandRequestContext("approval-command-1", 11, "approvals");

        // When
        var request = ApprovalCommands.Answer(
            new ApprovalAnswerIntent("approval-1", ApprovalDecision.Approve), context);

        // Then
        Assert.AreEqual("approval.answer", request.CommandType);
        Assert.AreEqual(2, request.Payload.Count);
        Assert.AreEqual("approval-1", ((NativeJsonString)request.Payload["approval_id"]!).Value);
        Assert.AreEqual("approve", ((NativeJsonString)request.Payload["decision"]!).Value);
    }
}
