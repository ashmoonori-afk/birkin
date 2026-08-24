namespace Birkin.Native.Shell.Presentation;

public sealed record WorkspaceSnapshotPresentation(
    long ProtocolVersion,
    string SessionId,
    long Cursor,
    string InstanceId,
    string ResetReason,
    string Transport,
    int PanelCount);
