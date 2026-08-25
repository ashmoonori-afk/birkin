using System.Windows.Controls;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class PrimaryColumnView : UserControl
{
    public PrimaryColumnView()
    {
        InitializeComponent();
        ConversationHost.Content = new ConversationView();
    }

    public void AttachWorkflow(ShellPresentationModel presentationModel, ShellCoordinator coordinator) =>
        ConversationHost.Content = new ConversationView(presentationModel, coordinator);
}
