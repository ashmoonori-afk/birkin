using System.Windows;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App;

public partial class MainWindow : Window
{
    public MainWindow(ShellPresentationModel presentationModel)
    {
        InitializeComponent();
        SnapshotView.DataContext = presentationModel;
    }
}
