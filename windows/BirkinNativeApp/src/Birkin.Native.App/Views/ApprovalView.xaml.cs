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
    private IReadOnlyList<PanelItemPresentation> _approvalRows = [];

    public ApprovalView()
    {
        InitializeComponent();
        ConfirmDecision = ConfirmWithDialog;
    }

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
    internal Func<PanelItemPresentation, ApprovalDecision, bool> ConfirmDecision { get; set; }

    public IReadOnlyList<PanelItemPresentation> ApprovalRows
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

    private void CopyFullValueClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (sender is Button { Tag: string value } && value.Length > 0)
        {
            Clipboard.SetText(value);
        }
    }

    private async Task AnswerAsync(object sender, ApprovalDecision decision)
    {
        if (_coordinator is not null
            && sender is Button
            {
                Tag: string approvalId,
                DataContext: PanelItemPresentation card,
            }
            && ConfirmDecision(card, decision))
        {
            ApprovalItems.IsEnabled = false;
            DecisionStatus.Visibility = Visibility.Visible;
            try
            {
                await _coordinator.AnswerApprovalAsync(
                    new ApprovalAnswerIntent(approvalId, decision),
                    CancellationToken.None);
            }
            finally
            {
                DecisionStatus.Visibility = Visibility.Collapsed;
                ApprovalItems.IsEnabled = true;
            }
        }
    }

    private bool ConfirmWithDialog(
        PanelItemPresentation card,
        ApprovalDecision decision)
    {
        var action = ResourceText(
            decision == ApprovalDecision.Approve
                ? "ApprovalConfirmApproveAction"
                : "ApprovalConfirmRejectAction");
        var result = MessageBox.Show(
            ConfirmationMessage(
                card,
                action,
                ResourceText("ApprovalNoDestination")),
            ResourceText("ApprovalConfirmTitle"),
            MessageBoxButton.YesNo,
            decision == ApprovalDecision.Approve
                ? MessageBoxImage.Warning
                : MessageBoxImage.Question);
        return result == MessageBoxResult.Yes;
    }

    internal static string ConfirmationMessage(
        PanelItemPresentation card,
        string action,
        string noDestination) =>
        $"{action}하시겠습니까?\n\n"
        + $"{card.Summary}\n"
        + $"{card.Destination ?? noDestination}\n"
        + card.OverwriteLabel;

    private string ResourceText(string key) =>
        FindResource(key) as string
        ?? throw new InvalidOperationException($"missing Korean string resource: {key}");

    private void ModelPropertyChanged(object? sender, PropertyChangedEventArgs eventArgs)
    {
        if (eventArgs.PropertyName == nameof(ShellPresentationModel.Workspace))
        {
            UpdateRows();
        }
    }

    private void UpdateRows() =>
        ApprovalRows = _model?.Workspace?.ApprovalRequests
            .Where(row =>
                string.Equals(row.Kind, "approval", StringComparison.Ordinal)
                && !row.Decided)
            .ToArray() ?? [];

    private void ViewUnloaded(object sender, RoutedEventArgs eventArgs)
    {
        if (_model is not null)
        {
            _model.PropertyChanged -= ModelPropertyChanged;
        }
    }
}
