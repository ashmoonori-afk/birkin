using System.Windows;
using System.Windows.Controls;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class NavigationColumnView : UserControl
{
    private ShellPresentationModel? _presentationModel;
    private ShellCoordinator? _coordinator;
    private Action? _showHistory;

    public NavigationColumnView() => InitializeComponent();

    public void AttachWorkflow(
        ShellPresentationModel presentationModel,
        ShellCoordinator coordinator,
        Action showHistory)
    {
        _presentationModel = presentationModel;
        _coordinator = coordinator;
        _showHistory = showHistory;
    }

    private async void CreateSessionClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (_coordinator is null)
        {
            return;
        }
        var sessionId = $"office-{DateTimeOffset.UtcNow:yyyyMMdd-HHmmss}";
        if (await _coordinator.CreateWorkspaceSessionAsync(sessionId, CancellationToken.None))
        {
            await _coordinator.SelectWorkspaceSessionAsync(sessionId, CancellationToken.None);
        }
    }

    private async void SelectSessionClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (_coordinator is null
            || sender is not Button { Tag: string sessionId }
            || string.Equals(sessionId, _presentationModel?.Workspace?.SessionId, StringComparison.Ordinal))
        {
            return;
        }
        await _coordinator.SelectWorkspaceSessionAsync(sessionId, CancellationToken.None);
    }

    private async void RenameSessionClicked(object sender, RoutedEventArgs eventArgs)
    {
        var name = SessionNameInput.Text.Trim();
        var sessionId = _presentationModel?.Workspace?.SessionId;
        if (_coordinator is null || string.IsNullOrEmpty(sessionId) || string.IsNullOrEmpty(name))
        {
            return;
        }
        await _coordinator.RenameWorkspaceSessionAsync(sessionId, name, CancellationToken.None);
        SessionNameInput.Clear();
    }

    private void ShowHistoryClicked(object sender, RoutedEventArgs eventArgs) => _showHistory?.Invoke();
}
