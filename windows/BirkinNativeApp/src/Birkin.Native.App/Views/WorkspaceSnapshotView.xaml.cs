using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Threading;
using Birkin.Native.App.Startup;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class WorkspaceSnapshotView : UserControl
{
    private ShellPresentationModel? _presentationModel;
    private IStartupRecovery? _startupRecovery;

    public WorkspaceSnapshotView()
    {
        InitializeComponent();
        InitializeLayoutBehavior();
        SelectRouteButton(ConversationRouteButton);
    }

    public WorkspaceSnapshotView(ShellPresentationModel presentationModel)
        : this() => DataContext = presentationModel;

    public void AttachWorkflow(ShellPresentationModel presentationModel, ShellCoordinator coordinator)
    {
        DataContext = presentationModel;
        NavigationColumnView.AttachWorkflow(
            presentationModel,
            coordinator,
            FocusActivity,
            FocusApprovals);
        PrimaryColumnView.AttachWorkflow(presentationModel, coordinator);
        ContextColumnView.AttachWorkflow(presentationModel, coordinator);
    }

    internal Task<bool> ImportDroppedFilesAsync(IReadOnlyList<string> paths) =>
        ContextColumnView.ImportDroppedFilesAsync(paths);

    internal void ReportImportSelectionError() =>
        ContextColumnView.ReportImportSelectionError();

    public void FocusApprovals()
    {
        ContextColumnView.ShowApprovalsWorkspace();
        ShowContextWorkspace();
        SelectRouteButton(ApprovalsRouteButton);
        ContextColumnView.FocusApprovals();
    }

    private void FocusActivity()
    {
        ContextColumnView.ShowReviewRail();
        if (_compactMode)
            ShowCompactPane(CompactPane.Context);
        else
        {
            if (_documentFocusRestore is not null)
                ToggleDocumentFocusMode();
            if (!_layout.Context.Visible)
                SetPanelVisibility(LayoutPanel.Context, true);
        }
        ContextColumnView.FocusActivity();
    }

    private void ConversationRouteClicked(object sender, RoutedEventArgs eventArgs) =>
        ShowConversationRoute(false);

    private void ResearchRouteClicked(object sender, RoutedEventArgs eventArgs) =>
        ShowConversationRoute(true);

    private void DocumentsRouteClicked(object sender, RoutedEventArgs eventArgs)
    {
        ContextColumnView.ShowDocumentsWorkspace();
        ShowContextWorkspace();
        SelectRouteButton(DocumentsRouteButton);
    }

    private void ApprovalsRouteClicked(object sender, RoutedEventArgs eventArgs)
    {
        ContextColumnView.ShowApprovalsWorkspace();
        ShowContextWorkspace();
        SelectRouteButton(ApprovalsRouteButton);
        ContextColumnView.FocusApprovals();
    }

    private void ShowConversationRoute(bool research)
    {
        ContextColumnView.ShowReviewRail();
        if (_compactMode)
            ShowCompactPane(CompactPane.Primary);
        else if (_documentFocusRestore is not null)
            ToggleDocumentFocusMode();
        PrimaryColumnView.ShowConversation(research);
        SelectRouteButton(research ? ResearchRouteButton : ConversationRouteButton);
        _ = PrimaryColumnView.Focus();
    }

    private void ShowContextWorkspace()
    {
        if (_compactMode)
            ShowCompactPane(CompactPane.Context);
        else if (_documentFocusRestore is null)
            ToggleDocumentFocusMode();
    }

    private void SelectRouteButton(Button selected)
    {
        BackToConversationButton.Visibility =
            ReferenceEquals(selected, DocumentsRouteButton)
            || ReferenceEquals(selected, ApprovalsRouteButton)
                ? Visibility.Visible
                : Visibility.Collapsed;
        foreach (var button in new[]
                 {
                     ConversationRouteButton, ResearchRouteButton,
                     DocumentsRouteButton, ApprovalsRouteButton,
                 })
        {
            button.SetResourceReference(
                Control.BackgroundProperty,
                ReferenceEquals(button, selected) ? "SelectedBrush" : "RaisedBrush");
            AutomationProperties.SetHelpText(
                button,
                ReferenceEquals(button, selected) ? "현재 보기" : "이 보기로 전환");
        }
    }

    public void AttachStartupRecovery(
        ShellPresentationModel presentationModel,
        IStartupRecovery startupRecovery)
    {
        _presentationModel = presentationModel;
        _startupRecovery = startupRecovery;
    }

    private async void RetryStartupClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (_presentationModel is null
            || _startupRecovery is null
            || sender is not Button button)
        {
            return;
        }

        button.IsEnabled = false;
        await Dispatcher.Yield(DispatcherPriority.ApplicationIdle);
        try
        {
            var failure = await _startupRecovery.RetryAsync();
            if (failure is null)
                _presentationModel.ClearStartupFailure();
            else
                _presentationModel.PresentStartupFailure(failure);
        }
        catch (OperationCanceledException)
        {
            // App shutdown owns this cancellation.
        }
        finally
        {
            button.IsEnabled = true;
        }
    }

    private async void ConfigureExecutableClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (_presentationModel is null
            || _startupRecovery is null
            || sender is not Button button)
        {
            return;
        }

        button.IsEnabled = false;
        await Dispatcher.Yield(DispatcherPriority.ApplicationIdle);
        try
        {
            var failure = await _startupRecovery.ConfigureExecutableAndRetryAsync(ExecutablePathInput.Text);
            if (failure is null)
                _presentationModel.ClearStartupFailure();
            else
                _presentationModel.PresentStartupFailure(failure);
        }
        catch (OperationCanceledException)
        {
            // App shutdown owns this cancellation.
        }
        finally
        {
            button.IsEnabled = true;
        }
    }

    private void StartupFailureTitleVisibilityChanged(
        object sender,
        DependencyPropertyChangedEventArgs eventArgs)
    {
        if (eventArgs.NewValue is true)
            _ = Dispatcher.BeginInvoke(new Action(() => StartupFailureTitle.Focus()));
    }
}
