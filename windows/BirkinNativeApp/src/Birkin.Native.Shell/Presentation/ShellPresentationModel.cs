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

    public ShellPresentationModel(SynchronizationContext synchronizationContext)
    {
        _synchronizationContext = synchronizationContext;
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public ConnectionPresentation Connection => _connection;

    public WorkspaceSnapshotPresentation? Workspace => _workspace;

    public OfficeWorkflowPresentation OfficeWorkflow => _officeWorkflow;

    public void PresentConnection(ConnectionPresentation presentation) =>
        _synchronizationContext.Post(
            _ =>
            {
                _connection = presentation;
                OnPropertyChanged(nameof(Connection));
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

    public void PresentOfficeWorkflow(OfficeWorkflowPresentation presentation) =>
        _synchronizationContext.Post(
            _ =>
            {
                _officeWorkflow = presentation;
                OnPropertyChanged(nameof(OfficeWorkflow));
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

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));

}
