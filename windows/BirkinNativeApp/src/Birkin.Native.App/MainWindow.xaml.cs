using System.ComponentModel;
using System.Windows;
using Birkin.Native.App.Startup;
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
}
