using System.Text;

namespace Birkin.Native.Shell.Presentation;

public sealed record MutationAvailabilityPresentation(bool IsEnabled, string DisabledReason)
{
    public static MutationAvailabilityPresentation PhaseOne { get; } =
        new(false, "현재 Windows 작업 변경 경로는 읽기 전용입니다.");
}

public sealed record ComposerPresentation(
    bool CanSend,
    bool CanInterrupt,
    bool CanResume,
    bool IsEnabled);

public sealed record ConversationRowPresentation(
    string Id,
    string Kind,
    string Text,
    string ActorId,
    long? Cursor)
{
    public string KindLabel => KoreanDecisionText.ConversationKind(Kind);
}

public sealed record WorkingMemoryRowPresentation(
    string Label,
    IReadOnlyList<string> Values,
    string EmptyState);

public sealed record WorkingMemoryPresentation(
    long Revision,
    IReadOnlyList<WorkingMemoryRowPresentation> Rows);

public sealed record ApprovalPolicyRowPresentation(
    string Label,
    string Category,
    string EffectiveState,
    string RequestedState,
    bool IsEnabled);

public sealed record PanelItemPresentation(
    string? Id,
    string? Kind,
    string? Summary,
    string? Description = null,
    string? Category = null,
    string? Risk = null,
    bool Sealed = false,
    bool Decided = false,
    string? SourceFilename = null,
    string? Destination = null,
    bool? OverwriteApproved = null,
    string? AuthorityDigest = null,
    string? Requester = null,
    string? RejectionResult = null,
    string? ExpiresAt = null,
    string? ReceiptRef = null,
    bool BackupExists = false,
    string? ValidationSummary = null,
    string? VisualValidationSummary = null,
    string? Status = null,
    string? OfficePhase = null,
    string? UpdatedAt = null,
    string? SessionId = null,
    string? Name = null,
    string? SourceType = null,
    string? Target = null,
    string? Assignee = null,
    string? DueDate = null,
    string? SourceDetail = null,
    string? SourceStatus = null,
    string? SourceDestination = null,
    string? SourceValidation = null,
    string? SourceFailure = null,
    string? SourceRollback = null,
    string? ApprovalAction = null,
    bool Recheckable = false,
    string? MailRecheckState = null,
    string? MailRecheckedAt = null)
{
    public bool HasSourceFilename => !string.IsNullOrWhiteSpace(SourceFilename);
    public bool HasDestination => !string.IsNullOrWhiteSpace(Destination);
    public bool HasAuthorityDigest => !string.IsNullOrWhiteSpace(AuthorityDigest);
    public bool HasReceipt => !string.IsNullOrWhiteSpace(ReceiptRef);
    public bool CanRollback =>
        HasReceipt
        && ReceiptExpiry is { } expiry
        && expiry > DateTimeOffset.UtcNow;
    public bool HasTrustDetails =>
        HasSourceFilename || HasDestination || HasAuthorityDigest;
    public string CategoryLabel => KoreanDecisionText.ApprovalCategory(Category);
    public string RiskLabel => KoreanDecisionText.ApprovalRisk(Risk);
    public string SealedLabel => KoreanDecisionText.ApprovalSeal(Sealed);
    public string OutcomeLabel =>
        KoreanDecisionText.ApprovalOutcome(Status, Category, MailRecheckState);
    public bool IsUnknownMailSend =>
        string.Equals(Category, "mail_send", StringComparison.Ordinal)
        && string.Equals(Status, "action_outcome_unknown", StringComparison.Ordinal);
    public bool CanAnswer => !Decided && !IsUnknownMailSend;
    public bool CanRecheck => IsUnknownMailSend && Recheckable;
    public string MailRecheckLabel =>
        KoreanDecisionText.MailRecheck(MailRecheckState);
    public string MailRecheckedAtLabel =>
        DateTimeOffset.TryParse(MailRecheckedAt, out var rechecked)
            ? $"마지막 확인 {rechecked.ToLocalTime():MM-dd HH:mm:ss}"
            : string.Empty;
    public string? DestinationDisplay => Abbreviate(Destination, 48);
    public string? AuthorityDigestDisplay => Abbreviate(AuthorityDigest, 27);
    public string RequesterLabel => $"요청자: {Requester ?? "확인할 수 없음"}";
    public string ExpiryLabel => $"만료: {ExpiresAt ?? "미지정"}";
    public string RollbackAvailabilityLabel => ReceiptExpiry switch
    {
        null => "되돌리기 기한을 확인할 수 없습니다.",
        DateTimeOffset expiry when expiry <= DateTimeOffset.UtcNow =>
            "되돌리기 기한이 지났습니다.",
        DateTimeOffset expiry when BackupExists =>
            $"원본은 백업되었으며 {expiry.Month}월 {expiry.Day}일까지 되돌리기 가능",
        DateTimeOffset expiry =>
            $"새 파일은 {expiry.Month}월 {expiry.Day}일까지 되돌리기 가능",
    };
    public string RejectionResultLabel =>
        RejectionResult ?? "거부하면 이 작업은 실행되지 않습니다.";
    public string CardAutomationId => AutomationId("card");
    public string RiskAutomationId => AutomationId("risk");
    public string SealedAutomationId => AutomationId("sealed");
    public string DescriptionAutomationId => AutomationId("description");
    public string SourceAutomationId => AutomationId("source");
    public string DestinationAutomationId => AutomationId("destination");
    public string OverwriteAutomationId => AutomationId("overwrite");
    public string RequesterAutomationId => AutomationId("requester");
    public string RejectionAutomationId => AutomationId("rejection");
    public string CopyDestinationAutomationId => AutomationId("copy-destination");
    public string CopyAuthorityAutomationId => AutomationId("copy-authority");
    public string RejectAutomationId => AutomationId("reject");
    public string ApproveAutomationId => AutomationId("approve");
    public string ReceiptDestinationAutomationId =>
        AutomationId("receipt.destination");
    public string ReceiptRetentionAutomationId =>
        AutomationId("receipt.retention");
    public string OpenFileAutomationId => AutomationId("receipt.open-file");
    public string OpenFolderAutomationId => AutomationId("receipt.open-folder");
    public string RollbackAutomationId => AutomationId("receipt.rollback");
    public string OutcomeAutomationId => AutomationId("outcome");
    public string ReceiptReferenceAutomationId =>
        AutomationId("receipt-reference");
    public string ValidationAutomationId => AutomationId("receipt.validation");
    public string VisualValidationAutomationId =>
        AutomationId("receipt.visual-validation");
    public string FollowUpAutomationId => AutomationId("receipt.follow-up");
    public string RecheckAutomationId => AutomationId("recheck");
    public string RecheckStateAutomationId => AutomationId("recheck-state");
    public string RecheckedAtAutomationId => AutomationId("rechecked-at");
    public string OfficePhaseLabel => OfficePhase switch
    {
        "inspection" => "자료 확인",
        "comparison" => "변경 내용 확인",
        "draft" => "내용 작성",
        "validation" => "검증",
        "export" => "저장 완료",
        _ => string.Empty,
    };
    public string LastUpdatedLabel =>
        DateTimeOffset.TryParse(UpdatedAt, out var updated)
            ? $"마지막 갱신 {updated.ToLocalTime():MM-dd HH:mm:ss}"
            : string.Empty;
    public string SessionDisplayName => Name ?? Summary ?? SessionId ?? "이름 없는 업무";
    public bool IsSelectedSession => string.Equals(Status, "selected", StringComparison.Ordinal);
    public bool IsWorkItem => string.Equals(Kind, "work_item", StringComparison.Ordinal);
    public bool CanOpenSource => IsWorkItem
        && SourceType is "conversation_id" or "artifact_uri" or "job_id" or "goal_slug"
        && !string.IsNullOrWhiteSpace(Target)
        && !string.Equals(SourceStatus, "unavailable", StringComparison.Ordinal);
    public bool CanComplete => IsWorkItem && !string.Equals(Status, "최근 완료", StringComparison.Ordinal);
    public string SourceTypeLabel => SourceType switch
    {
        "conversation_id" => "관련 업무",
        "artifact_uri" => "Office 원본",
        "job_id" => "결과 영수증",
        "goal_slug" => "관련 목표",
        _ => "관련 자료 없음",
    };
    public string SourceDisplay => SourceType == "artifact_uri" ? Path.GetFileName(Target) ?? string.Empty : Target ?? string.Empty;
    public bool HasSourceDetail => !string.IsNullOrWhiteSpace(SourceDetail);
    public bool HasReceiptDetails => SourceType == "job_id"
        && new[] { SourceDestination, SourceValidation, SourceFailure, SourceRollback }
            .Any(value => !string.IsNullOrWhiteSpace(value));
    public string SourceStatusLabel => SourceStatus switch
    {
        "active" => "목표 진행 중",
        "paused" => "목표 일시 중지",
        "done" => "목표 완료",
        "input_captured" => "요청 접수",
        "outcome_declared" => "결과 정의",
        "operations_proposed" => "변경안 작성",
        "preview_ready" => "미리보기 준비",
        "approval_requested" => "승인 대기",
        "approved" => "승인 완료",
        "executed" => "변경 실행",
        "validated" => "검증 완료",
        "exported" => "저장 완료",
        "rejected" => "요청 거부",
        "failed" => "작업 실패",
        "rolled_back" => "되돌림 완료",
        "unavailable" => "원본을 찾을 수 없음",
        _ => SourceStatus ?? string.Empty,
    };
    public string SourceActionLabel => SourceType switch
    {
        "job_id" => "결과 영수증 확인",
        "goal_slug" => "관련 목표 확인",
        _ => "원본 열기",
    };
    public DateTime? DueDateValue => DateTime.TryParse(DueDate, out var value) ? value : null;
    public string OverwriteLabel =>
        KoreanDecisionText.ApprovalOverwrite(OverwriteApproved);
    public bool IsWorkItemApproval =>
        string.Equals(Category, "work_item", StringComparison.Ordinal);
    public string WorkItemChangeLabel => ApprovalAction switch
    {
        "create" => "수행할 변경: 후속 업무 생성",
        "update" => "수행할 변경: 후속 업무 수정",
        "complete" => "수행할 변경: 후속 업무 완료",
        "confirm_meeting" => "수행할 변경: 회의 후속 업무 생성",
        _ => "수행할 변경: 후속 업무 반영",
    };

    private string AutomationId(string part) =>
        $"approval.{part}.{Id ?? "unknown"}";

    private DateTimeOffset? ReceiptExpiry =>
        DateTimeOffset.TryParse(ExpiresAt, out var expiry) ? expiry : null;

    private static string? Abbreviate(string? value, int limit)
    {
        if (string.IsNullOrEmpty(value))
        {
            return value;
        }
        var runes = value.EnumerateRunes().ToArray();
        if (runes.Length <= limit)
        {
            return value;
        }
        var left = (limit - 3) / 2;
        var right = limit - left - 3;
        return string.Concat(runes[..left].Select(rune => rune.ToString()))
            + "..."
            + string.Concat(runes[^right..].Select(rune => rune.ToString()));
    }
}

public sealed record TerminalPresentation(bool IsAvailable, int SourceCount);
