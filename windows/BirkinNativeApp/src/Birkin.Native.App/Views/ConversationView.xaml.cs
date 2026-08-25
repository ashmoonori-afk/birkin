using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class ConversationView : UserControl
{
    private ShellPresentationModel? _model;
    private ShellCoordinator? _coordinator;
    private bool _presentingDraft;

    public ConversationView() => InitializeComponent();

    public ConversationView(ShellPresentationModel model, ShellCoordinator coordinator) : this()
    {
        _model = model;
        _coordinator = coordinator;
        DataContext = model;
        model.PropertyChanged += ModelPropertyChanged;
        PresentDraft();
        Unloaded += ViewUnloaded;
    }

    private void DraftChanged(object sender, TextChangedEventArgs eventArgs)
    {
        if (!_presentingDraft)
        {
            _coordinator?.SetConversationDraft(DraftBox.Text);
        }
    }

    private async void SendClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (_coordinator is not null)
        {
            await _coordinator.SendConversationAsync(CancellationToken.None);
        }
    }

    private void ModelPropertyChanged(object? sender, PropertyChangedEventArgs eventArgs)
    {
        if (eventArgs.PropertyName == nameof(ShellPresentationModel.OfficeWorkflow))
        {
            PresentDraft();
        }
    }

    private void PresentDraft()
    {
        if (_model is null || string.Equals(DraftBox.Text, _model.OfficeWorkflow.Draft, StringComparison.Ordinal))
        {
            return;
        }
        _presentingDraft = true;
        DraftBox.Text = _model.OfficeWorkflow.Draft;
        DraftBox.CaretIndex = DraftBox.Text.Length;
        _presentingDraft = false;
    }

    private void ViewUnloaded(object sender, RoutedEventArgs eventArgs)
    {
        if (_model is not null)
        {
            _model.PropertyChanged -= ModelPropertyChanged;
        }
    }
}
