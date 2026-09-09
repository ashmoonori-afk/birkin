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

    internal Task<bool> ImportDroppedFilesAsync(
        IReadOnlyList<string> paths) =>
        ((OfficeView)OfficeHost.Content).ImportDroppedFilesAsync(paths);

    internal void ReportImportSelectionError() =>
        ((OfficeView)OfficeHost.Content).ReportImportSelectionError();

    public void FocusApprovals()
    {
        ContextScroll.ScrollToTop();
        _ = ApprovalsRegion.Focus();
    }

    public void FocusActivity()
    {
        _ = ActivityRegion.Focus();
        ActivityRegion.BringIntoView();
    }

    public void ShowReviewRail()
    {
        ApprovalsRegion.Visibility = System.Windows.Visibility.Visible;
        ActivityRegion.Visibility = System.Windows.Visibility.Visible;
        BrowserRegion.Visibility = System.Windows.Visibility.Visible;
        OfficeRegion.Visibility = System.Windows.Visibility.Visible;
        OfficeRegion.Height = double.NaN;
    }

    public void ShowDocumentsWorkspace()
    {
        ApprovalsRegion.Visibility = System.Windows.Visibility.Collapsed;
        ActivityRegion.Visibility = System.Windows.Visibility.Collapsed;
        BrowserRegion.Visibility = System.Windows.Visibility.Collapsed;
        OfficeRegion.Visibility = System.Windows.Visibility.Visible;
        OfficeRegion.Height = double.NaN;
        _ = OfficeRegion.Focus();
    }

    public void ShowApprovalsWorkspace()
    {
        ActivityRegion.Visibility = System.Windows.Visibility.Collapsed;
        BrowserRegion.Visibility = System.Windows.Visibility.Collapsed;
        OfficeRegion.Visibility = System.Windows.Visibility.Collapsed;
        ApprovalsRegion.Visibility = System.Windows.Visibility.Visible;
        _ = ApprovalsRegion.Focus();
    }
}
