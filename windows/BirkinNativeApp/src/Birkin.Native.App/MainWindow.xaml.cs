using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Input;
using Birkin.Native.App.Startup;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App;

public partial class MainWindow : Window
{
    public MainWindow(ShellPresentationModel presentationModel)
    {
        InitializeComponent();
        SnapshotView.DataContext = presentationModel;
        if (CompositionRoot.CoordinatorFor(presentationModel) is { } coordinator)
        {
            SnapshotView.AttachWorkflow(presentationModel, coordinator);
        }
    }

    public MainWindow(ShellPresentationModel presentationModel, ShellCoordinator coordinator)
    {
        InitializeComponent();
        SnapshotView.AttachWorkflow(presentationModel, coordinator);
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
            ? "Drop one file to copy it into Birkin's session jail"
            : "Choose exactly one file";
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
