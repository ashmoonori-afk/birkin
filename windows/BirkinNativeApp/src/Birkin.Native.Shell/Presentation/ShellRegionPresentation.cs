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
    string? ExpiresAt = null)
{
    public bool HasSourceFilename => !string.IsNullOrWhiteSpace(SourceFilename);
    public bool HasDestination => !string.IsNullOrWhiteSpace(Destination);
    public bool HasAuthorityDigest => !string.IsNullOrWhiteSpace(AuthorityDigest);
    public bool HasTrustDetails =>
        HasSourceFilename || HasDestination || HasAuthorityDigest;
    public string CategoryLabel => (Category ?? "unknown").Replace('_', ' ');
    public string RiskLabel => $"{Risk?.ToUpperInvariant() ?? "UNKNOWN"} RISK";
    public string SealedLabel => Sealed ? "SEALED" : "NOT SEALED";
    public string? DestinationDisplay => Abbreviate(Destination, 48);
    public string? AuthorityDigestDisplay => Abbreviate(AuthorityDigest, 27);
    public string RequesterLabel => $"REQUESTED BY: {Requester ?? "Unavailable"}";
    public string ExpiryLabel => $"EXPIRES: {ExpiresAt ?? "Not specified"}";
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
    public string OverwriteLabel => OverwriteApproved switch
    {
        true => "WARNING: Existing file may be replaced",
        false => "SAFE: Existing file must not already exist",
        null => "UNKNOWN: Overwrite authority unavailable",
    };

    private string AutomationId(string part) =>
        $"approval.{part}.{Id ?? "unknown"}";

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
