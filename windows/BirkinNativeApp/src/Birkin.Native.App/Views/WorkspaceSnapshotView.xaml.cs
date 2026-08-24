using System.Windows.Controls;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class WorkspaceSnapshotView : UserControl
{
    public WorkspaceSnapshotView() => InitializeComponent();

    public WorkspaceSnapshotView(ShellPresentationModel presentationModel)
        : this() => DataContext = presentationModel;
}
