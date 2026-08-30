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

    [DataTestMethod]
    [DataRow(
        "E_CONNECTION_NOT_READY",
        "아직 연결되지 않았습니다. 연결이 완료된 뒤 다시 시도하세요.")]
    [DataRow(
        "E_CAPABILITY_EXPIRED",
        "세션 권한이 만료되었습니다. 다시 연결한 뒤 시도하세요.")]
    [DataRow(
        "E_COMMAND_UNADVERTISED",
        "현재 서버에서 이 작업을 지원하지 않습니다. 앱과 Birkin을 업데이트한 뒤 다시 시도하세요.")]
    [DataRow(
        "E_PROJECTION_FORBIDS_MUTATION",
        "현재 화면 상태에서는 변경할 수 없습니다. 최신 상태를 불러온 뒤 다시 시도하세요.")]
    public void DisabledReason_WhenMapped_ExposesKoreanGuidance(
        string code,
        string expected)
    {
        // Given / When
        var availability = new MutationAvailability(false, code);

        // Then
        Assert.AreEqual(expected, availability.DisabledReasonText);
    }

    [DataTestMethod]
    [DataRow(WorkflowCommandState.Idle, "")]
    [DataRow(WorkflowCommandState.PendingReceipt, "요청을 보내는 중입니다.")]
    [DataRow(WorkflowCommandState.AcceptedPendingProjection, "결과를 확인하는 중입니다.")]
    [DataRow(WorkflowCommandState.Refused, "요청이 거부되었습니다.")]
    public void WorkflowState_WhenMapped_ExposesKoreanText(
        WorkflowCommandState state,
        string expected)
    {
        // Given / When
        var workflow = OfficeWorkflowPresentation.Empty with { CommandState = state };

        // Then
        Assert.AreEqual(expected, workflow.CommandStateText);
    }

    [DataTestMethod]
    [DataRow("user", "사용자")]
    [DataRow("assistant", "Birkin")]
    [DataRow("system", "시스템")]
    [DataRow("tool", "도구")]
    [DataRow("future", "메시지")]
    public void ConversationKind_WhenMapped_ExposesKoreanLabel(
        string kind,
        string expected)
    {
        // Given / When
        var row = new ConversationRowPresentation(
            "message-1",
            kind,
            "본문",
            "actor",
            1);

        // Then
        Assert.AreEqual(expected, row.KindLabel);
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
        var refused = workflow.Refuse(
            "command-1",
            "E_STALE_CURSOR",
            "cursor is stale",
            false,
            27);

        // Then
        Assert.AreEqual(" exact draft \n", refused.Draft);
        Assert.AreEqual(WorkflowCommandState.Refused, refused.CommandState);
        Assert.AreEqual(27L, refused.CurrentCursor);
        Assert.AreEqual(
            "작업 상태가 이미 변경되었습니다. 최신 내용을 확인한 뒤 다시 시도하세요.",
            refused.RefusalText);
        StringAssert.Contains(refused.RefusalDiagnosticDetail, "cursor is stale");
    }

    [DataTestMethod]
    [DataRow(
        "E_CONNECTION_NOT_READY",
        "아직 연결되지 않았습니다. 연결이 완료된 뒤 다시 시도하세요.")]
    [DataRow(
        "E_CAPABILITY_EXPIRED",
        "세션 권한이 만료되었습니다. 다시 연결한 뒤 시도하세요.")]
    [DataRow(
        "E_COMMAND_UNADVERTISED",
        "현재 서버에서 이 작업을 지원하지 않습니다. 앱과 Birkin을 업데이트한 뒤 다시 시도하세요.")]
    [DataRow(
        "E_PROJECTION_FORBIDS_MUTATION",
        "현재 화면 상태에서는 변경할 수 없습니다. 최신 상태를 불러온 뒤 다시 시도하세요.")]
    [DataRow(
        "E_OFFICE_JOB_REQUEST_REQUIRED",
        "이 작업은 Office 승인 요청이 필요합니다. 승인 요청을 만든 뒤 계속하세요.")]
    [DataRow(
        "E_STALE_CURSOR",
        "작업 상태가 이미 변경되었습니다. 최신 내용을 확인한 뒤 다시 시도하세요.")]
    public void ErrorCode_WhenKnown_MapsToBoundedKoreanGuidance(
        string code,
        string expected)
    {
        // When
        var presentation = KoreanDecisionText.Error(
            code,
            "server detail",
            retryable: false,
            currentCursor: 12);

        // Then
        Assert.AreEqual(expected, presentation.UserMessage);
        StringAssert.Contains(presentation.DiagnosticDetail, code);
        StringAssert.Contains(presentation.DiagnosticDetail, "server detail");
    }

    [TestMethod]
    public void ErrorCode_WhenUnknown_UsesKoreanFallbackAndPreservesDiagnostic()
    {
        // When
        var presentation = KoreanDecisionText.Error(
            "E_FUTURE",
            "bounded future detail",
            retryable: true);

        // Then
        Assert.AreEqual(
            "요청을 처리할 수 없습니다. 잠시 후 다시 시도하고 계속되면 오류 코드를 확인하세요.",
            presentation.UserMessage);
        StringAssert.Contains(presentation.DiagnosticDetail, "E_FUTURE");
        StringAssert.Contains(presentation.DiagnosticDetail, "bounded future detail");
    }

    [TestMethod]
    public void Workflow_WhenApprovalDecisionAwaitsReceipt_DisablesRepeatedDecision()
    {
        // Given / When
        var workflow = OfficeWorkflowPresentation.Empty.Begin("approval-command", "approval.answer");

        // Then
        Assert.IsTrue(workflow.HasPendingCommand);
    }

    [DataTestMethod]
    [DataRow(WorkflowCommandState.PendingReceipt, "명령을 전송하고 있습니다.")]
    [DataRow(WorkflowCommandState.AcceptedPendingProjection, "결과를 화면에 반영하고 있습니다.")]
    public void Workflow_WhenCommandIsPending_ProvidesKoreanProgressCopy(
        WorkflowCommandState state,
        string expected)
    {
        var workflow = OfficeWorkflowPresentation.Empty with { CommandState = state };

        Assert.IsTrue(workflow.HasPendingCommand);
        Assert.AreEqual(expected, workflow.CommandProgressText);
    }

    [DataTestMethod]
    [DataRow(WorkflowCommandState.Idle)]
    [DataRow(WorkflowCommandState.Refused)]
    public void Workflow_WhenCommandIsNotPending_HidesProgressCopy(
        WorkflowCommandState state)
    {
        var workflow = OfficeWorkflowPresentation.Empty with { CommandState = state };

        Assert.IsFalse(workflow.HasPendingCommand);
        Assert.AreEqual(string.Empty, workflow.CommandProgressText);
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
