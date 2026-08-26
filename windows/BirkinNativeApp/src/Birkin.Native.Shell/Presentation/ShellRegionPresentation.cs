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
    string? Summary);

public sealed record TerminalItemPresentation(
    string TerminalId,
    string Cwd,
    string Display,
    long OutputSequence,
    string State,
    long? ExitStatus,
    long Columns,
    long Rows,
    bool IsReadOnly);

public sealed record TerminalPresentation(
    bool IsCreateEnabled,
    string? DisabledReason,
    IReadOnlyList<TerminalItemPresentation> Items)
{
    public TerminalPresentation(bool isAvailable, int sourceCount)
        : this(false, "E_COMMAND_UNADVERTISED", [])
    {
        if (isAvailable || sourceCount != 0)
            throw new ArgumentException("Only the legacy (false, 0) tuple is supported.");
    }

    public bool IsAvailable => Items.Count > 0;
    public int SourceCount => Items.Count;
    public string? TerminalId => Items.FirstOrDefault()?.TerminalId;
    public string Display => Items.FirstOrDefault()?.Display ?? string.Empty;
    public long OutputSequence => Items.FirstOrDefault()?.OutputSequence ?? 0;
    public string? State => Items.FirstOrDefault()?.State;
    public long? ExitStatus => Items.FirstOrDefault()?.ExitStatus;
    public long Columns => Items.FirstOrDefault()?.Columns ?? 0;
    public long Rows => Items.FirstOrDefault()?.Rows ?? 0;
    public bool IsReadOnly => Items.FirstOrDefault()?.IsReadOnly ?? true;
}
