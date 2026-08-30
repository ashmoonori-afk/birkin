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
    MutationAvailability ConversationInterrupt,
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
        new(
            Disabled,
            Disabled,
            Disabled,
            Disabled,
            Disabled,
            Disabled,
            Disabled,
            Disabled,
            Disabled,
            Disabled);
}

public sealed record OfficeWorkflowPresentation(
    string Draft,
    string? CommandId,
    string? CommandType,
    WorkflowCommandState CommandState,
    long? AcceptedCursor,
    long? CurrentCursor,
    string? RefusalCode,
    MutationAvailabilitySet Availability,
    string? RefusalMessage = null,
    bool? RefusalRetryable = null)
{
    public static OfficeWorkflowPresentation Empty { get; } =
        new(string.Empty, null, null, WorkflowCommandState.Idle, null, null, null, MutationAvailabilitySet.None);

    public bool HasPendingCommand =>
        CommandState is WorkflowCommandState.PendingReceipt
            or WorkflowCommandState.AcceptedPendingProjection;

    public string CommandProgressText => CommandState switch
    {
        WorkflowCommandState.PendingReceipt => "명령을 전송하고 있습니다.",
        WorkflowCommandState.AcceptedPendingProjection => "결과를 화면에 반영하고 있습니다.",
        _ => string.Empty,
    };

    public string CommandStateText =>
        KoreanDecisionText.WorkflowState(CommandState);

    public string? RefusalText =>
        RefusalCode is { } code
            ? KoreanDecisionText.Error(
                code,
                RefusalMessage,
                RefusalRetryable,
                CurrentCursor).UserMessage
            : null;

    public string? RefusalDiagnosticDetail =>
        RefusalCode is { } code
            ? KoreanDecisionText.Error(
                code,
                RefusalMessage,
                RefusalRetryable,
                CurrentCursor).DiagnosticDetail
            : null;

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
        RefusalMessage = null,
        RefusalRetryable = null,
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
        string refusalMessage,
        bool refusalRetryable,
        long? currentCursor) =>
        string.Equals(CommandId, commandId, StringComparison.Ordinal)
            ? this with
            {
                CommandState = WorkflowCommandState.Refused,
                RefusalCode = refusalCode,
                RefusalMessage = refusalMessage,
                RefusalRetryable = refusalRetryable,
                CurrentCursor = currentCursor,
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
                RefusalMessage = null,
                RefusalRetryable = null,
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
        RefusalMessage = null,
        RefusalRetryable = null,
    };
}
