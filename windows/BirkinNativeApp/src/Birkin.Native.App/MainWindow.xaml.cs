using System.Windows;
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
}
