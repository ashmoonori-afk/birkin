using System.Globalization;
using System.Text;

namespace Birkin.Native.Shell.Presentation;

public sealed record MutationAvailabilityPresentation(bool IsEnabled, string DisabledReason)
{
    public static MutationAvailabilityPresentation PhaseOne { get; } =
        new(false, "Windows phase 1 is read-only.");
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
    long? Cursor);

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
    public string CategoryLabel => (Category ?? "unknown").Replace('_', ' ');
    public string RiskLabel => $"{Risk?.ToUpperInvariant() ?? "UNKNOWN"} RISK";
    public string SealedLabel => Sealed ? "SEALED" : "NOT SEALED";
    public string OutcomeLabel => Status switch
    {
        "approved" => "Approved",
        "rejected" => "Rejected",
        "answered_elsewhere" => "Answered elsewhere",
        "expired" => "Expired",
        "failed" => "Failed",
        _ => CultureInfo.InvariantCulture.TextInfo.ToTitleCase(
            (Status ?? "pending").Replace('_', ' ')),
    };
    public string? DestinationDisplay => Abbreviate(Destination, 48);
    public string? AuthorityDigestDisplay => Abbreviate(AuthorityDigest, 27);
    public string RequesterLabel => $"REQUESTED BY: {Requester ?? "Unavailable"}";
    public string ExpiryLabel => $"EXPIRES: {ExpiresAt ?? "Not specified"}";
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
        RejectionResult ?? "Rejection outcome unavailable";
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
    public string OverwriteLabel => OverwriteApproved switch
    {
        true => "WARNING: Existing file may be replaced",
        false => "SAFE: Existing file must not already exist",
        null => "UNKNOWN: Overwrite authority unavailable",
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
