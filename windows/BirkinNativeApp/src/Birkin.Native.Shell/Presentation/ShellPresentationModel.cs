using System.ComponentModel;
using System.Runtime.CompilerServices;
using Birkin.Native.Shell.Connection;

namespace Birkin.Native.Shell.Presentation;

public sealed class ShellPresentationModel : INotifyPropertyChanged
{
    private readonly SynchronizationContext _synchronizationContext;
    private ConnectionPresentation _connection = ConnectionPresentation.Create(ConnectionState.Disconnected);
    private WorkspaceSnapshotPresentation? _workspace;
    private OfficeWorkflowPresentation _officeWorkflow = OfficeWorkflowPresentation.Empty;
    private TerminalWorkflowPresentation _terminalWorkflow = TerminalWorkflowPresentation.Empty;

    public ShellPresentationModel(SynchronizationContext synchronizationContext)
    {
        _synchronizationContext = synchronizationContext;
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public ConnectionPresentation Connection => _connection;

    public WorkspaceSnapshotPresentation? Workspace => _workspace;

    public OfficeWorkflowPresentation OfficeWorkflow => _officeWorkflow;

    public TerminalWorkflowPresentation TerminalWorkflow => _terminalWorkflow;

    public void PresentConnection(ConnectionPresentation presentation) =>
        _synchronizationContext.Post(
            _ =>
            {
                _connection = presentation;
                OnPropertyChanged(nameof(Connection));
            },
            null);

    public void PresentConnection(
        ConnectionPresentation connection,
        OfficeWorkflowPresentation workflow,
        TerminalWorkflowPresentation terminalWorkflow) =>
        _synchronizationContext.Post(
            _ =>
            {
                _connection = connection;
                _officeWorkflow = workflow;
                _terminalWorkflow = terminalWorkflow;
                OnPropertyChanged(nameof(Connection));
                OnPropertyChanged(nameof(OfficeWorkflow));
                OnPropertyChanged(nameof(TerminalWorkflow));
            },
            null);

    public void PresentSnapshot(WorkspaceSnapshotPresentation presentation, Action published) =>
        _synchronizationContext.Post(
            _ =>
            {
                _workspace = presentation;
                OnPropertyChanged(nameof(Workspace));
                published();
            },
            null);

    public void PresentSnapshot(
        WorkspaceSnapshotPresentation presentation,
        OfficeWorkflowPresentation workflow,
        TerminalWorkflowPresentation terminalWorkflow,
        Action published) =>
        _synchronizationContext.Post(
            _ =>
            {
                _workspace = presentation;
                _officeWorkflow = workflow;
                _terminalWorkflow = terminalWorkflow;
                OnPropertyChanged(nameof(Workspace));
                OnPropertyChanged(nameof(OfficeWorkflow));
                OnPropertyChanged(nameof(TerminalWorkflow));
                published();
            },
            null);

    public void PresentOfficeWorkflow(OfficeWorkflowPresentation presentation) =>
        PresentWorkflows(presentation, TerminalWorkflow);

    public void PresentWorkflows(
        OfficeWorkflowPresentation presentation,
        TerminalWorkflowPresentation terminalPresentation) =>
        _synchronizationContext.Post(
            _ =>
            {
                _officeWorkflow = presentation;
                _terminalWorkflow = terminalPresentation;
                OnPropertyChanged(nameof(OfficeWorkflow));
                OnPropertyChanged(nameof(TerminalWorkflow));
            },
            null);

    public void PresentReadySnapshot(WorkspaceSnapshotPresentation presentation, Action published) =>
        _synchronizationContext.Post(
            _ =>
            {
                _connection = ConnectionPresentation.Create(ConnectionState.Ready);
                _workspace = presentation;
                OnPropertyChanged(nameof(Connection));
                OnPropertyChanged(nameof(Workspace));
                published();
            },
            null);

    public void PresentReadySnapshot(
        ConnectionPresentation connection,
        WorkspaceSnapshotPresentation presentation,
        OfficeWorkflowPresentation workflow,
        TerminalWorkflowPresentation terminalWorkflow,
        Action published) =>
        _synchronizationContext.Post(
            _ =>
            {
                _connection = connection;
                _workspace = presentation;
                _officeWorkflow = workflow;
                _terminalWorkflow = terminalWorkflow;
                OnPropertyChanged(nameof(Connection));
                OnPropertyChanged(nameof(Workspace));
                OnPropertyChanged(nameof(OfficeWorkflow));
                OnPropertyChanged(nameof(TerminalWorkflow));
                published();
            },
            null);

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));

}
