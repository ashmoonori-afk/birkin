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
    string? Status = null)
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
    public string OutcomeLabel => KoreanDecisionText.ApprovalOutcome(Status);
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
    public string OverwriteLabel =>
        KoreanDecisionText.ApprovalOverwrite(OverwriteApproved);

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
