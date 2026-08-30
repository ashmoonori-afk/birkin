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
    private StartupFailurePresentation? _startupFailure;

    public ShellPresentationModel(SynchronizationContext synchronizationContext)
    {
        _synchronizationContext = synchronizationContext;
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public ConnectionPresentation Connection => _connection;

    public WorkspaceSnapshotPresentation? Workspace => _workspace;

    public OfficeWorkflowPresentation OfficeWorkflow => _officeWorkflow;

    public StartupFailurePresentation? StartupFailure => _startupFailure;

    public bool HasStartupFailure => _startupFailure is not null;

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
        OfficeWorkflowPresentation workflow) =>
        _synchronizationContext.Post(
            _ =>
            {
                _connection = connection;
                _officeWorkflow = workflow;
                OnPropertyChanged(nameof(Connection));
                OnPropertyChanged(nameof(OfficeWorkflow));
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
        Action published) =>
        _synchronizationContext.Post(
            _ =>
            {
                _workspace = presentation;
                _officeWorkflow = workflow;
                OnPropertyChanged(nameof(Workspace));
                OnPropertyChanged(nameof(OfficeWorkflow));
                published();
            },
            null);

    public void PresentOfficeWorkflow(OfficeWorkflowPresentation presentation) =>
        _synchronizationContext.Post(
            _ =>
            {
                _officeWorkflow = presentation;
                OnPropertyChanged(nameof(OfficeWorkflow));
            },
            null);

    public void PresentStartupFailure(StartupFailurePresentation failure) =>
        _synchronizationContext.Post(
            _ =>
            {
                _startupFailure = failure;
                _connection = ConnectionPresentation.Failed(failure.ErrorCode);
                OnPropertyChanged(nameof(StartupFailure));
                OnPropertyChanged(nameof(HasStartupFailure));
                OnPropertyChanged(nameof(Connection));
            },
            null);

    public void ClearStartupFailure() =>
        _synchronizationContext.Post(
            _ =>
            {
                _startupFailure = null;
                OnPropertyChanged(nameof(StartupFailure));
                OnPropertyChanged(nameof(HasStartupFailure));
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
        Action published) =>
        _synchronizationContext.Post(
            _ =>
            {
                _connection = connection;
                _workspace = presentation;
                _officeWorkflow = workflow;
                OnPropertyChanged(nameof(Connection));
                OnPropertyChanged(nameof(Workspace));
                OnPropertyChanged(nameof(OfficeWorkflow));
                published();
            },
            null);

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));

}
