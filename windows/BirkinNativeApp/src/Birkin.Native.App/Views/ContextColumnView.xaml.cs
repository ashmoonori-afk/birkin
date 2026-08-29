using System.Windows.Controls;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class ContextColumnView : UserControl
{
    public ContextColumnView()
    {
        InitializeComponent();
        ApprovalHost.Content = new ApprovalView();
        OfficeHost.Content = new OfficeView();
    }

    public void AttachWorkflow(ShellPresentationModel presentationModel, ShellCoordinator coordinator)
    {
        ApprovalHost.Content = new ApprovalView(presentationModel, coordinator);
        OfficeHost.Content = new OfficeView(presentationModel, coordinator);
    }

    public void FocusApprovals()
    {
        ContextScroll.ScrollToTop();
        _ = ApprovalsRegion.Focus();
    }
}
