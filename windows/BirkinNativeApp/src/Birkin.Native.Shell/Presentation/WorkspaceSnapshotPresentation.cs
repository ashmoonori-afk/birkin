using Birkin.Native.Protocol.Projection;

namespace Birkin.Native.Shell.Presentation;

public sealed record WorkspaceSnapshotPresentation
{
    public WorkspaceSnapshotPresentation(
        long ProtocolVersion,
        string SessionId,
        long Cursor,
        string InstanceId,
        string ResetReason,
        string Transport,
        int PanelCount)
        : this(
            ProtocolVersion,
            SessionId,
            Cursor,
            InstanceId,
            ResetReason,
            Transport,
            PanelCount,
            string.Empty,
            [],
            new ComposerPresentation(false, false, false, false),
            new WorkingMemoryPresentation(0, []),
            [],
            [],
            [],
            [],
            [],
            new TerminalPresentation(false, 0),
            MutationAvailabilityPresentation.PhaseOne)
    {
    }

    public WorkspaceSnapshotPresentation(
        long ProtocolVersion,
        string SessionId,
        long Cursor,
        string InstanceId,
        string ResetReason,
        string Transport,
        int PanelCount,
        string PythonConnection,
        IReadOnlyList<ConversationRowPresentation> Conversation,
        ComposerPresentation Composer,
        WorkingMemoryPresentation WorkingMemory,
        IReadOnlyList<ApprovalPolicyRowPresentation> Approvals,
        IReadOnlyList<PanelItemPresentation> ApprovalRequests,
        IReadOnlyList<PanelItemPresentation> Activity,
        IReadOnlyList<PanelItemPresentation> Browser,
        IReadOnlyList<PanelItemPresentation> Office,
        TerminalPresentation Terminal,
        MutationAvailabilityPresentation MutationAvailability)
    {
        this.ProtocolVersion = ProtocolVersion;
        this.SessionId = SessionId;
        this.Cursor = Cursor;
        this.InstanceId = InstanceId;
        this.ResetReason = ResetReason;
        this.Transport = Transport;
        this.PanelCount = PanelCount;
        this.PythonConnection = PythonConnection;
        this.Conversation = Conversation;
        this.Composer = Composer;
        this.WorkingMemory = WorkingMemory;
        this.Approvals = Approvals;
        this.ApprovalRequests = ApprovalRequests;
        this.Activity = Activity;
        this.Browser = Browser;
        this.Office = Office;
        this.Terminal = Terminal;
        this.MutationAvailability = MutationAvailability;
    }

    public long ProtocolVersion { get; }
    public string SessionId { get; }
    public long Cursor { get; }
    public string InstanceId { get; }
    public string ResetReason { get; }
    public string Transport { get; }
    public int PanelCount { get; }
    public string PythonConnection { get; }
    public IReadOnlyList<ConversationRowPresentation> Conversation { get; }
    public ComposerPresentation Composer { get; }
    public WorkingMemoryPresentation WorkingMemory { get; }
    public IReadOnlyList<ApprovalPolicyRowPresentation> Approvals { get; }
    public IReadOnlyList<PanelItemPresentation> ApprovalRequests { get; }
    public IReadOnlyList<PanelItemPresentation> Activity { get; }
    public IReadOnlyList<PanelItemPresentation> Browser { get; }
    public IReadOnlyList<PanelItemPresentation> Office { get; }
    public TerminalPresentation Terminal { get; }
    public MutationAvailabilityPresentation MutationAvailability { get; }

    public static WorkspaceSnapshotPresentation FromProjection(
        NativeProjectionState state,
        string transport) => WorkspaceProjectionMapper.Map(state, transport);
}
