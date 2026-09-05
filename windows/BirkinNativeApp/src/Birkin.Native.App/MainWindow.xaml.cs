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
    private LayoutStore? _layoutStore;
    private bool _layoutInitialized;
    private ShellPresentationModel? _attentionModel;
    private WindowsApprovalAttention? _windowsAttention;

    public MainWindow(ShellPresentationModel presentationModel)
    {
        InitializeComponent();
        InitializeLayout();
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
        InitializeLayout();
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
        InitializeLayout();
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
        _layoutStore?.Dispose();
        _layoutStore = null;
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
        InitializeLayout();
        SnapshotView.AttachWorkflow(presentationModel, coordinator);
        SnapshotView.AttachStartupRecovery(presentationModel, startupRecovery);
        AttachAttention(presentationModel, approvalToast);
    }

    private void InitializeLayout()
    {
        if (_layoutInitialized) return;
        _layoutInitialized = true;
        _layoutStore = new LayoutStore(Dispatcher);
        var state = _layoutStore.Load();
        _layoutStore.Seed(state);
        Width = state.Window.Width;
        Height = state.Window.Height;
        if (state.Window.Left is { } left && state.Window.Top is { } top
            && IntersectsVirtualScreen(left, top, Width, Height))
        {
            WindowStartupLocation = WindowStartupLocation.Manual;
            Left = left;
            Top = top;
        }
        SnapshotView.AttachLayout(state, SaveLayout);
        Loaded += (_, _) =>
        {
            if (state.Window.State == LayoutWindowMode.Maximized) WindowState = WindowState.Maximized;
            SnapshotView.ApplyAvailableWidth(ActualWidth);
        };
        SizeChanged += (_, _) =>
        {
            SnapshotView.ApplyAvailableWidth(ActualWidth);
            SaveWindowDebounced();
        };
        LocationChanged += (_, _) => SaveWindowDebounced();
        StateChanged += (_, _) => SaveWindowDebounced();
    }

    private void SaveLayout(LayoutState state, bool immediate) =>
        _layoutStore?.Save(state with { Window = CaptureWindow() }, immediate);

    private void SaveWindowDebounced()
    {
        if (!IsLoaded) return;
        _layoutStore?.Save(SnapshotView.LayoutState with { Window = CaptureWindow() }, windowOnly: true);
    }

    private LayoutWindowState CaptureWindow()
    {
        var bounds = WindowState == WindowState.Maximized ? RestoreBounds : new Rect(Left, Top, ActualWidth, ActualHeight);
        var width = bounds.Width > 0 ? bounds.Width : Width;
        var height = bounds.Height > 0 ? bounds.Height : Height;
        return new LayoutWindowState(
            Math.Max(MinWidth, width), Math.Max(MinHeight, height),
            double.IsFinite(bounds.Left) ? bounds.Left : null,
            double.IsFinite(bounds.Top) ? bounds.Top : null,
            WindowState == WindowState.Maximized ? LayoutWindowMode.Maximized : LayoutWindowMode.Normal);
    }

    private static bool IntersectsVirtualScreen(double left, double top, double width, double height)
    {
        var screenLeft = SystemParameters.VirtualScreenLeft;
        var screenTop = SystemParameters.VirtualScreenTop;
        var screenRight = screenLeft + SystemParameters.VirtualScreenWidth;
        var screenBottom = screenTop + SystemParameters.VirtualScreenHeight;
        return left < screenRight
            && left > screenLeft - width
            && top < screenBottom
            && top > screenTop - height;
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
