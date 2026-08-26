using System.Windows;
using System.ComponentModel;
using System.Windows.Controls;
using System.Windows.Input;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class TerminalView : UserControl
{
    private ShellPresentationModel? _model;
    private readonly ShellCoordinator? _coordinator;

    public TerminalView()
    {
        InitializeComponent();
        DataContextChanged += ViewDataContextChanged;
        Unloaded += ViewUnloaded;
    }

    public TerminalView(ShellPresentationModel model, ShellCoordinator coordinator) : this()
    {
        _coordinator = coordinator;
        _model = model;
        _model.PropertyChanged += ModelPropertyChanged;
        DataContext = model;
        PresentOutput();
    }

    private void ViewDataContextChanged(object sender, DependencyPropertyChangedEventArgs eventArgs)
    {
        if (_model is not null)
        {
            _model.PropertyChanged -= ModelPropertyChanged;
        }
        _model = eventArgs.NewValue as ShellPresentationModel;
        if (_model is not null)
        {
            _model.PropertyChanged += ModelPropertyChanged;
        }
        PresentOutput();
    }

    private void ModelPropertyChanged(object? sender, PropertyChangedEventArgs eventArgs)
    {
        if (eventArgs.PropertyName == nameof(ShellPresentationModel.Workspace))
        {
            PresentOutput();
        }
    }

    private void PresentOutput() => OutputText.Text = _model?.Workspace?.Terminal.Display ?? string.Empty;

    private void ViewUnloaded(object sender, RoutedEventArgs eventArgs)
    {
        if (_model is not null)
        {
            _model.PropertyChanged -= ModelPropertyChanged;
        }
    }

    private async void CreateClicked(object sender, RoutedEventArgs eventArgs)
    {
        var workspaceCwd = _model?.TerminalWorkflow.WorkspaceCwd;
        if (_coordinator is not null && !string.IsNullOrWhiteSpace(workspaceCwd))
        {
            await _coordinator.CreateTerminalAsync(workspaceCwd, CancellationToken.None);
        }
    }

    private async void SendClicked(object sender, RoutedEventArgs eventArgs) => await SendInputAsync();

    private async void InputKeyDown(object sender, KeyEventArgs eventArgs)
    {
        if (eventArgs.Key != Key.Enter || Keyboard.Modifiers.HasFlag(ModifierKeys.Shift))
        {
            return;
        }

        eventArgs.Handled = true;
        await SendInputAsync();
    }

    private async Task SendInputAsync()
    {
        var terminalId = CurrentTerminalId();
        if (_coordinator is null || terminalId is null || InputBox.Text.Length == 0)
        {
            return;
        }

        if (await _coordinator.SendTerminalInputAsync(
                terminalId,
                InputBox.Text + "\r\n",
                CancellationToken.None))
        {
            InputBox.Clear();
        }
    }

    private async void ResizeClicked(object sender, RoutedEventArgs eventArgs)
    {
        var terminalId = CurrentTerminalId();
        if (_coordinator is not null
            && terminalId is not null
            && long.TryParse(ColumnsBox.Text, out var columns)
            && long.TryParse(RowsBox.Text, out var rows)
            && columns is >= 1 and <= 1000
            && rows is >= 1 and <= 1000)
        {
            await _coordinator.ResizeTerminalAsync(terminalId, columns, rows, CancellationToken.None);
        }
    }

    private async void InterruptClicked(object sender, RoutedEventArgs eventArgs)
    {
        var terminalId = CurrentTerminalId();
        if (_coordinator is not null && terminalId is not null)
        {
            await _coordinator.InterruptTerminalAsync(terminalId, CancellationToken.None);
        }
    }

    private async void CloseClicked(object sender, RoutedEventArgs eventArgs)
    {
        var terminalId = CurrentTerminalId();
        if (_coordinator is not null && terminalId is not null)
        {
            await _coordinator.CloseTerminalAsync(terminalId, CancellationToken.None);
        }
    }

    private string? CurrentTerminalId() =>
        _model?.TerminalWorkflow.TerminalId ?? _model?.Workspace?.Terminal.TerminalId;
}
