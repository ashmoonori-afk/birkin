namespace Birkin.Native.Shell.Presentation;

public enum WorkflowCommandState
{
    Idle,
    PendingReceipt,
    AcceptedPendingProjection,
    Refused,
}

public sealed record MutationAvailabilitySet(
    MutationAvailability ConversationSend,
    MutationAvailability FileImport,
    MutationAvailability ApprovalAnswer,
    MutationAvailability OfficeCreate,
    MutationAvailability OfficeSelect,
    MutationAvailability OfficeOpen,
    MutationAvailability OfficeCompare,
    MutationAvailability OfficeDraft,
    MutationAvailability OfficeConvert)
{
    private static readonly MutationAvailability Disabled = new(false, "E_CONNECTION_NOT_READY");

    public static MutationAvailabilitySet None { get; } =
        new(Disabled, Disabled, Disabled, Disabled, Disabled, Disabled, Disabled, Disabled, Disabled);
}

public sealed record OfficeWorkflowPresentation(
    string Draft,
    string? CommandId,
    string? CommandType,
    WorkflowCommandState CommandState,
    long? AcceptedCursor,
    long? CurrentCursor,
    string? RefusalCode,
    string? FailureMessage,
    MutationAvailabilitySet Availability)
{
    public static OfficeWorkflowPresentation Empty { get; } =
        new(string.Empty, null, null, WorkflowCommandState.Idle, null, null, null, null, MutationAvailabilitySet.None);

    public bool HasPendingCommand =>
        CommandState is WorkflowCommandState.PendingReceipt
            or WorkflowCommandState.AcceptedPendingProjection;

    public string? UserFacingFailure => RefusalCode switch
    {
        null => null,
        "E_COMMAND_FAILED" => "Birkin couldn't complete the command. Check the local workspace and try again.",
        _ => FailureMessage,
    };

    public OfficeWorkflowPresentation WithDraft(string draft) => this with { Draft = draft };

    public OfficeWorkflowPresentation WithAvailability(MutationAvailabilitySet availability) =>
        this with { Availability = availability };

    public OfficeWorkflowPresentation Begin(string commandId, string commandType) => this with
    {
        CommandId = commandId,
        CommandType = commandType,
        CommandState = WorkflowCommandState.PendingReceipt,
        AcceptedCursor = null,
        CurrentCursor = null,
        RefusalCode = null,
        FailureMessage = null,
    };

    public OfficeWorkflowPresentation Accept(string commandId, long acceptedCursor) =>
        string.Equals(CommandId, commandId, StringComparison.Ordinal)
            ? this with
            {
                Draft = string.Equals(CommandType, "chat.send", StringComparison.Ordinal)
                    ? string.Empty
                    : Draft,
                CommandState = WorkflowCommandState.AcceptedPendingProjection,
                AcceptedCursor = acceptedCursor,
            }
            : this;

    public OfficeWorkflowPresentation Refuse(
        string commandId,
        string refusalCode,
        long? currentCursor,
        string? failureMessage = null) =>
        string.Equals(CommandId, commandId, StringComparison.Ordinal)
            ? this with
            {
                CommandState = WorkflowCommandState.Refused,
                RefusalCode = refusalCode,
                CurrentCursor = currentCursor,
                FailureMessage = failureMessage,
            }
            : this;

    public OfficeWorkflowPresentation ResolveFromProjection(string commandId) =>
        string.Equals(CommandId, commandId, StringComparison.Ordinal)
            ? this with
            {
                Draft = string.Equals(CommandType, "chat.send", StringComparison.Ordinal)
                    ? string.Empty
                    : Draft,
                CommandId = null,
                CommandType = null,
                CommandState = WorkflowCommandState.Idle,
                AcceptedCursor = null,
                CurrentCursor = null,
                RefusalCode = null,
                FailureMessage = null,
            }
            : this;

    public OfficeWorkflowPresentation ClearAuthority() => this with
    {
        CommandId = null,
        CommandType = null,
        CommandState = WorkflowCommandState.Idle,
        AcceptedCursor = null,
        CurrentCursor = null,
        RefusalCode = null,
        FailureMessage = null,
    };
}
