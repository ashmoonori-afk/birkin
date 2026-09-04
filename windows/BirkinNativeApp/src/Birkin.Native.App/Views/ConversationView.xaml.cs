using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class ConversationView : UserControl
{
    private readonly ViewCommandLifetime _commandLifetime = new();
    private ShellPresentationModel? _model;
    private ShellCoordinator? _coordinator;
    private bool _presentingDraft;
    private bool _hasMarkedText;
    private bool _restoreDraftFocus;

    public ConversationView()
    {
        InitializeComponent();
        TextCompositionManager.AddPreviewTextInputStartHandler(
            DraftBox,
            DraftCompositionStarted);
        TextCompositionManager.AddPreviewTextInputUpdateHandler(
            DraftBox,
            DraftCompositionStarted);
        TextCompositionManager.AddPreviewTextInputHandler(
            DraftBox,
            DraftCompositionCompleted);
    }

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
            _restoreDraftFocus = true;
            await _commandLifetime.RunAsync(
                token => _coordinator.SendConversationAsync(token));
            ScheduleDraftFocusRestore();
        }
    }

    private async void StopClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (_coordinator is not null)
        {
            _restoreDraftFocus = true;
            await _commandLifetime.RunAsync(
                token => _coordinator.InterruptConversationAsync(token));
            ScheduleDraftFocusRestore();
        }
    }

    private async void DraftPreviewKeyDown(
        object sender,
        KeyEventArgs eventArgs)
    {
        if (!WindowsSendKeyPolicy.ShouldSend(
            eventArgs.Key,
            Keyboard.Modifiers,
            _hasMarkedText))
        {
            return;
        }
        eventArgs.Handled = true;
        await HandleDraftKeyAsync(
            eventArgs.Key,
            Keyboard.Modifiers);
    }

    internal async Task<bool> HandleDraftKeyAsync(
        Key key,
        ModifierKeys modifiers)
    {
        if (!WindowsSendKeyPolicy.ShouldSend(
            key,
            modifiers,
            _hasMarkedText))
        {
            return false;
        }
        if (_coordinator is not null)
        {
            _restoreDraftFocus = true;
            await _commandLifetime.RunAsync(
                token => _coordinator.SendConversationAsync(token));
            ScheduleDraftFocusRestore();
        }
        return true;
    }

    private void DraftCompositionStarted(
        object sender,
        TextCompositionEventArgs eventArgs) =>
        _hasMarkedText = true;

    private void DraftCompositionCompleted(
        object sender,
        TextCompositionEventArgs eventArgs) =>
        _hasMarkedText = false;

    private void DraftKeyboardFocusLost(
        object sender,
        KeyboardFocusChangedEventArgs eventArgs) =>
        _hasMarkedText = false;

    private void ModelPropertyChanged(object? sender, PropertyChangedEventArgs eventArgs)
    {
        if (eventArgs.PropertyName == nameof(ShellPresentationModel.OfficeWorkflow))
        {
            PresentDraft();
            ScheduleDraftFocusRestore();
        }
    }

    private void ScheduleDraftFocusRestore()
    {
        if (!_restoreDraftFocus)
        {
            return;
        }
        _ = Dispatcher.BeginInvoke(
            DispatcherPriority.Input,
            new Action(TryRestoreDraftFocus));
    }

    private void TryRestoreDraftFocus()
    {
        if (_restoreDraftFocus
            && DraftBox.IsEnabled
            && DraftBox.Focus())
        {
            _restoreDraftFocus = false;
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
        _hasMarkedText = false;
        _restoreDraftFocus = false;
        _commandLifetime.Dispose();
        if (_model is not null)
        {
            _model.PropertyChanged -= ModelPropertyChanged;
        }
    }
}
