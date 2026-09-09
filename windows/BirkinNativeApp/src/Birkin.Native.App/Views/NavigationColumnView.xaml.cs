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
    private Action? _showApprovals;

    public NavigationColumnView() => InitializeComponent();

    public void AttachWorkflow(
        ShellPresentationModel presentationModel,
        ShellCoordinator coordinator,
        Action showHistory,
        Action? showApprovals = null)
    {
        _presentationModel = presentationModel;
        _coordinator = coordinator;
        _showHistory = showHistory;
        _showApprovals = showApprovals;
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

    private async void CompleteWorkItemClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (_coordinator is not null && sender is Button { Tag: PanelItemPresentation { Id: string id } })
        {
            WorkItemFeedback.Text = "승인 요청 중…";
            var requested = await _coordinator.CompleteWorkItemAsync(id, CancellationToken.None);
            WorkItemFeedback.Text = requested ? "승인 대기 중" : "요청 실패";
            if (requested)
            {
                _ = Dispatcher.BeginInvoke(new Action(() => _showApprovals?.Invoke()));
            }
        }
    }

    private async void OpenWorkItemSourceClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (sender is not Button { Tag: PanelItemPresentation item } || string.IsNullOrWhiteSpace(item.Target))
        {
            return;
        }
        if (item.SourceType == "conversation_id" && _coordinator is not null)
        {
            await _coordinator.SelectWorkspaceSessionAsync(item.Target, CancellationToken.None);
        }
        else if (_coordinator is not null && sender is Button { CommandParameter: Expander receiptDetails })
        {
            WorkItemFeedback.Text = "원본 확인 중…";
            var result = await _coordinator.OpenWorkItemSourceAsync(item.Id!, CancellationToken.None);
            if (result is null)
            {
                WorkItemFeedback.Text = "원본 확인 실패";
            }
            else if (result.SourceType == "goal_slug")
            {
                WorkItemFeedback.Text = string.IsNullOrWhiteSpace(result.SessionId)
                    ? "목표 상세를 확인했습니다."
                    : result.Navigated
                        ? "관련 목표 업무로 이동했습니다."
                        : "목표 상세를 확인했습니다.";
            }
            else if (result.SourceType == "job_id")
            {
                WorkItemFeedback.Text = "결과 영수증을 열었습니다.";
                receiptDetails.IsExpanded = true;
            }
            else
            {
                WorkItemFeedback.Text = "Office 원본을 열었습니다.";
            }
        }
        else
        {
            _showHistory?.Invoke();
        }
    }

    private async void UpdateWorkItemClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (_coordinator is null
            || sender is not Button { Tag: PanelItemPresentation { Id: string id }, Parent: StackPanel panel })
        {
            return;
        }
        var assignee = panel.Children.OfType<TextBox>().SingleOrDefault()?.Text.Trim();
        var dueDate = panel.Children.OfType<DatePicker>().SingleOrDefault()?.SelectedDate;
        if (assignee is not null)
        {
            WorkItemFeedback.Text = "승인 요청 중…";
            var requested = await _coordinator.UpdateWorkItemAsync(id, string.IsNullOrEmpty(assignee) ? null : assignee, dueDate, CancellationToken.None);
            WorkItemFeedback.Text = requested ? "승인 대기 중" : "요청 실패";
            if (requested)
            {
                _ = Dispatcher.BeginInvoke(new Action(() => _showApprovals?.Invoke()));
            }
        }
    }
}
