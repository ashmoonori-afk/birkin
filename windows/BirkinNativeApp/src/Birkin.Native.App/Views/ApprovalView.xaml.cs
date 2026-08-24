using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class ApprovalView : UserControl, INotifyPropertyChanged
{
    private readonly ShellPresentationModel? _model;
    private readonly ShellCoordinator? _coordinator;
    private IReadOnlyList<ConversationRowPresentation> _approvalRows = [];

    public ApprovalView() => InitializeComponent();

    public ApprovalView(ShellPresentationModel model, ShellCoordinator coordinator) : this()
    {
        _model = model;
        _coordinator = coordinator;
        DataContext = model;
        model.PropertyChanged += ModelPropertyChanged;
        UpdateRows();
        Unloaded += ViewUnloaded;
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    public IReadOnlyList<ConversationRowPresentation> ApprovalRows
    {
        get => _approvalRows;
        private set
        {
            _approvalRows = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(ApprovalRows)));
        }
    }

    private async void ApproveClicked(object sender, RoutedEventArgs eventArgs) =>
        await AnswerAsync(sender, ApprovalDecision.Approve);

    private async void RejectClicked(object sender, RoutedEventArgs eventArgs) =>
        await AnswerAsync(sender, ApprovalDecision.Reject);

    private async Task AnswerAsync(object sender, ApprovalDecision decision)
    {
        if (_coordinator is not null && sender is Button { Tag: string approvalId })
        {
            await _coordinator.AnswerApprovalAsync(
                new ApprovalAnswerIntent(approvalId, decision),
                CancellationToken.None);
        }
    }

    private void ModelPropertyChanged(object? sender, PropertyChangedEventArgs eventArgs)
    {
        if (eventArgs.PropertyName == nameof(ShellPresentationModel.Workspace))
        {
            UpdateRows();
        }
    }

    private void UpdateRows() => ApprovalRows = _model?.Workspace?.Conversation
        .Where(row => string.Equals(row.Kind, "approval", StringComparison.Ordinal)).ToArray() ?? [];

    private void ViewUnloaded(object sender, RoutedEventArgs eventArgs)
    {
        if (_model is not null)
        {
            _model.PropertyChanged -= ModelPropertyChanged;
        }
    }
}
