using System.Runtime.InteropServices;
using System.ComponentModel;
using System.Windows;
using System.Windows.Input;
using Birkin.Native.App.Startup;
using Birkin.Native.App.Views;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App;

public partial class MainWindow : Window
{
    private readonly ApprovalAttentionTracker _approvalAttention = new();
    private ShellPresentationModel? _attentionModel;
    private WindowsApprovalAttention? _windowsAttention;

    public MainWindow(ShellPresentationModel presentationModel)
    {
        InitializeComponent();
        SnapshotView.DataContext = presentationModel;
        if (CompositionRoot.CoordinatorFor(presentationModel) is { } coordinator)
        {
            SnapshotView.AttachWorkflow(presentationModel, coordinator);
        }
        AttachAttention(presentationModel, null);
    }

    internal MainWindow(
        ShellPresentationModel presentationModel,
        IApprovalToast approvalToast)
    {
        InitializeComponent();
        SnapshotView.DataContext = presentationModel;
        if (CompositionRoot.CoordinatorFor(presentationModel) is { } coordinator)
        {
            SnapshotView.AttachWorkflow(presentationModel, coordinator);
        }
        AttachAttention(presentationModel, approvalToast);
    }

    public MainWindow(ShellPresentationModel presentationModel, ShellCoordinator coordinator)
    {
        InitializeComponent();
        SnapshotView.AttachWorkflow(presentationModel, coordinator);
        AttachAttention(presentationModel, null);
    }

    internal void ShowApprovals()
    {
        if (!IsVisible)
        {
            Show();
        }
        if (WindowState == WindowState.Minimized)
        {
            WindowState = WindowState.Normal;
        }
        _ = Activate();
        SnapshotView.FocusApprovals();
    }

    private void AttachAttention(
        ShellPresentationModel presentationModel,
        IApprovalToast? approvalToast)
    {
        _attentionModel = presentationModel;
        _windowsAttention = new WindowsApprovalAttention(
            this,
            toast: approvalToast);
        presentationModel.PropertyChanged += PresentationChanged;
        Closed += WindowClosed;
    }

    private void PresentationChanged(
        object? sender,
        PropertyChangedEventArgs eventArgs)
    {
        if (eventArgs.PropertyName != nameof(ShellPresentationModel.Workspace)
            || _attentionModel?.Workspace is not { } workspace
            || _windowsAttention is null)
        {
            return;
        }
        var signal = _approvalAttention.Observe(workspace.ApprovalRequests);
        _windowsAttention.SetPending(_approvalAttention.PendingCount);
        if (signal is not null)
        {
            _windowsAttention.Notify(signal);
        }
    }

    private void WindowClosed(object? sender, EventArgs eventArgs)
    {
        if (_attentionModel is not null)
        {
            _attentionModel.PropertyChanged -= PresentationChanged;
        }
        _windowsAttention?.Dispose();
    }

    public MainWindow(
        ShellPresentationModel presentationModel,
        ShellCoordinator coordinator,
        IStartupRecovery startupRecovery)
        : this(presentationModel, coordinator, startupRecovery, null)
    {
    }

    internal MainWindow(
        ShellPresentationModel presentationModel,
        ShellCoordinator coordinator,
        IStartupRecovery startupRecovery,
        IApprovalToast? approvalToast)
    {
        InitializeComponent();
        SnapshotView.AttachWorkflow(presentationModel, coordinator);
        SnapshotView.AttachStartupRecovery(presentationModel, startupRecovery);
        AttachAttention(presentationModel, approvalToast);
    }

    private void WindowDragEntered(object sender, DragEventArgs eventArgs) =>
        PresentDrag(eventArgs);

    private void WindowDragOver(object sender, DragEventArgs eventArgs) =>
        PresentDrag(eventArgs);

    private void WindowDragLeft(object sender, DragEventArgs eventArgs)
    {
        DropOverlay.Visibility = Visibility.Collapsed;
        eventArgs.Handled = true;
    }

    private async void WindowDropped(object sender, DragEventArgs eventArgs)
    {
        var paths = DroppedPaths(eventArgs.Data);
        DropOverlay.Visibility = Visibility.Collapsed;
        eventArgs.Handled = true;
        if (paths.Count == 0)
        {
            SnapshotView.ReportImportSelectionError();
            return;
        }
        _ = await SnapshotView.ImportDroppedFilesAsync(paths);
    }

    private void PresentDrag(DragEventArgs eventArgs)
    {
        var paths = DroppedPaths(eventArgs.Data);
        var eligible = OfficeFileSelection.Select(paths) is not null;
        DropOverlayText.Text = eligible
            ? "파일 하나를 안전한 작업공간으로 가져오세요"
            : "파일을 하나만 선택하세요";
        DropOverlay.Visibility = Visibility.Visible;
        eventArgs.Effects = eligible
            ? DragDropEffects.Copy
            : DragDropEffects.None;
        eventArgs.Handled = true;
    }

    private static IReadOnlyList<string> DroppedPaths(IDataObject data)
    {
        try
        {
            return data.GetDataPresent(DataFormats.FileDrop)
                && data.GetData(DataFormats.FileDrop) is string[] paths
                    ? paths
                    : [];
        }
        catch (COMException)
        {
            return [];
        }
    }
}
