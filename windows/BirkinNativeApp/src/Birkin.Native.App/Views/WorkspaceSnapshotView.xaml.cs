using System.Windows.Controls;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class WorkspaceSnapshotView : UserControl
{
    public WorkspaceSnapshotView() => InitializeComponent();

    public WorkspaceSnapshotView(ShellPresentationModel presentationModel)
        : this() => DataContext = presentationModel;

    public void AttachWorkflow(ShellPresentationModel presentationModel, ShellCoordinator coordinator)
    {
        DataContext = presentationModel;
        PrimaryColumnView.AttachWorkflow(presentationModel, coordinator);
        ContextColumnView.AttachWorkflow(presentationModel, coordinator);
    }

    public void FocusApprovals() => ContextColumnView.FocusApprovals();
}
