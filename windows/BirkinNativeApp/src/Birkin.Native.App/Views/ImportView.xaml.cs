using System.Windows;
using System.Windows.Controls;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class ImportView : UserControl
{
    private readonly ShellCoordinator? _coordinator;

    public ImportView() => InitializeComponent();

    public ImportView(ShellPresentationModel model, ShellCoordinator coordinator) : this()
    {
        _coordinator = coordinator;
        DataContext = model;
    }

    private async void ImportClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (_coordinator is not null && PathBox.Text.Length > 0)
        {
            await _coordinator.ImportAsync(new FileImportIntent(PathBox.Text), CancellationToken.None);
        }
    }
}
