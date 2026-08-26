namespace Birkin.Native.Shell.Presentation;

public enum TerminalCommandState
{
    Idle,
    PendingReceipt,
    AcceptedPendingProjection,
    ApprovalRequired,
    Refused,
}

public sealed record TerminalMutationAvailability(
    MutationAvailability Input,
    MutationAvailability Resize,
    MutationAvailability Interrupt,
    MutationAvailability Close)
{
    private static readonly MutationAvailability Disabled =
        new(false, "E_PROJECTION_FORBIDS_MUTATION");

    public static TerminalMutationAvailability None { get; } =
        new(Disabled, Disabled, Disabled, Disabled);
}

public sealed record TerminalWorkflowPresentation
{
    public MutationAvailability CreateAvailability { get; init; } =
        new(false, "E_CONNECTION_NOT_READY");
    public string? WorkspaceCwd { get; init; }
    public string? TerminalId { get; init; }
    public string DraftInput { get; init; } = string.Empty;
    public string? PendingCommandId { get; init; }
    public string? PendingCommandType { get; init; }
    public TerminalCommandState CommandState { get; init; } = TerminalCommandState.Idle;
    public long? AcceptedCursor { get; init; }
    public long? CurrentCursor { get; init; }
    public long NextInputSequence { get; init; } = 1;
    public string? ApprovalId { get; init; }
    public string? RefusalCode { get; init; }
    public string? UserFacingFailure { get; init; }
    public TerminalMutationAvailability MutationAvailability { get; init; } =
        TerminalMutationAvailability.None;

    public static TerminalWorkflowPresentation Empty { get; } = new();

    public bool HasPendingCommand => CommandState is
        TerminalCommandState.PendingReceipt or TerminalCommandState.AcceptedPendingProjection;

    public TerminalWorkflowPresentation Begin(string commandId, string commandType) => this with
    {
        PendingCommandId = commandId,
        PendingCommandType = commandType,
        CommandState = TerminalCommandState.PendingReceipt,
        AcceptedCursor = null,
        CurrentCursor = null,
        RefusalCode = null,
        UserFacingFailure = null,
    };

    public TerminalWorkflowPresentation Accept(
        string commandId,
        long acceptedCursor,
        string? terminalId = null,
        long? nextInputSequence = null) =>
        string.Equals(PendingCommandId, commandId, StringComparison.Ordinal)
            ? this with
            {
                TerminalId = terminalId ?? TerminalId,
                CommandState = TerminalCommandState.AcceptedPendingProjection,
                AcceptedCursor = acceptedCursor,
                CurrentCursor = CurrentCursor is { } currentCursor
                    ? Math.Max(currentCursor, acceptedCursor)
                    : acceptedCursor,
                NextInputSequence = nextInputSequence ?? NextInputSequence,
                ApprovalId = null,
                RefusalCode = null,
                UserFacingFailure = null,
            }
            : this;

    public TerminalWorkflowPresentation Refuse(NativeTerminalRefusal refusal) =>
        string.Equals(PendingCommandId, refusal.CommandId, StringComparison.Ordinal)
            ? this with
            {
                CommandState = refusal.ApprovalId is null
                    ? TerminalCommandState.Refused
                    : TerminalCommandState.ApprovalRequired,
                CurrentCursor = refusal.CurrentCursor ?? CurrentCursor,
                ApprovalId = refusal.ApprovalId,
                RefusalCode = refusal.Code,
                UserFacingFailure = refusal.Guidance,
            }
            : this;

    public TerminalWorkflowPresentation Resolve(string commandId, bool exited, long currentCursor)
    {
        if (!string.Equals(PendingCommandId, commandId, StringComparison.Ordinal))
        {
            return exited
                ? this with { TerminalId = null, CurrentCursor = currentCursor }
                : this with { CurrentCursor = currentCursor };
        }
        if (CommandState == TerminalCommandState.PendingReceipt)
        {
            return this with { CurrentCursor = currentCursor };
        }
        return this with
        {
            TerminalId = exited ? null : TerminalId,
            PendingCommandId = null,
            PendingCommandType = null,
            CommandState = TerminalCommandState.Idle,
            AcceptedCursor = null,
            CurrentCursor = currentCursor,
            RefusalCode = null,
            UserFacingFailure = null,
        };
    }

    public TerminalWorkflowPresentation ClearAuthority(bool preserveWorkspaceCwd = false) => this with
    {
        WorkspaceCwd = preserveWorkspaceCwd ? WorkspaceCwd : null,
        TerminalId = null,
        PendingCommandId = null,
        PendingCommandType = null,
        CommandState = TerminalCommandState.Idle,
        AcceptedCursor = null,
        ApprovalId = null,
        RefusalCode = null,
        UserFacingFailure = null,
        MutationAvailability = TerminalMutationAvailability.None,
    };
}

public sealed record NativeTerminalRefusal(
    string Code,
    string CommandId,
    long? CurrentCursor,
    string? ApprovalId,
    string Guidance);
