using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Presentation;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class OfficeWorkflowPresentationTests
{
    [TestMethod]
    public void ForCommand_WhenEveryAuthoritySignalPermits_IsEnabled()
    {
        // Given / When
        var availability = MutationAvailability.ForCommand(
            "chat.send",
            new MutationAuthoritySnapshot(
                ConnectionState.Ready, true, new HashSet<string>(["chat.send"]), true));

        // Then
        Assert.IsTrue(availability.IsEnabled);
    }

    [DataTestMethod]
    [DataRow(ConnectionState.Disconnected, true, true, true)]
    [DataRow(ConnectionState.Ready, false, true, true)]
    [DataRow(ConnectionState.Ready, true, false, true)]
    [DataRow(ConnectionState.Ready, true, true, false)]
    public void ForCommand_WhenAnyAuthoritySignalMissing_IsDisabled(
        ConnectionState state, bool capabilityPresent, bool advertised, bool projectionPermits)
    {
        // Given / When
        var availability = MutationAvailability.ForCommand(
            "chat.send",
            new MutationAuthoritySnapshot(
                state,
                capabilityPresent,
                advertised ? new HashSet<string>(["chat.send"]) : new HashSet<string>(),
                projectionPermits));

        // Then
        Assert.IsFalse(availability.IsEnabled);
    }

    [TestMethod]
    public void Workflow_WhenReceiptAccepted_TracksCorrelationWithoutCanonicalSuccess()
    {
        // Given
        var workflow = OfficeWorkflowPresentation.Empty.WithDraft("한글 draft").Begin("command-1", "chat.send");

        // When
        var accepted = workflow.Accept("command-1", 12);

        // Then
        Assert.AreEqual(string.Empty, accepted.Draft);
        Assert.AreEqual(WorkflowCommandState.AcceptedPendingProjection, accepted.CommandState);
        Assert.AreEqual(12L, accepted.AcceptedCursor);
    }

    [TestMethod]
    public void Workflow_WhenStaleCursorRefused_PreservesExactDraftAndSurfacesCursor()
    {
        // Given
        var workflow = OfficeWorkflowPresentation.Empty.WithDraft(" exact draft \n").Begin("command-1", "chat.send");

        // When
        var refused = workflow.Refuse("command-1", "E_STALE_CURSOR", 27);

        // Then
        Assert.AreEqual(" exact draft \n", refused.Draft);
        Assert.AreEqual(WorkflowCommandState.Refused, refused.CommandState);
        Assert.AreEqual(27L, refused.CurrentCursor);
    }

    [TestMethod]
    public void Workflow_WhenApprovalDecisionAwaitsReceipt_DisablesRepeatedDecision()
    {
        // Given / When
        var workflow = OfficeWorkflowPresentation.Empty.Begin("approval-command", "approval.answer");

        // Then
        Assert.IsTrue(workflow.HasPendingCommand);
    }

    [TestMethod]
    public void Workflow_WhenAuthorityClears_PreservesDraftAndClearsPending()
    {
        // Given
        var workflow = OfficeWorkflowPresentation.Empty.WithDraft("draft").Begin("command-1", "approval.answer");

        // When
        var cleared = workflow.ClearAuthority();

        // Then
        Assert.AreEqual("draft", cleared.Draft);
        Assert.IsNull(cleared.CommandId);
        Assert.AreEqual(WorkflowCommandState.Idle, cleared.CommandState);
    }
}
