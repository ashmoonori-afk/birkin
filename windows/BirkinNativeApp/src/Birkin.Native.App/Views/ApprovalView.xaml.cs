using System.ComponentModel;
using System.Diagnostics;
using System.IO;
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
    private IReadOnlyList<PanelItemPresentation> _decidedApprovalRows = [];

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
    internal Func<PanelItemPresentation, ApprovalDecision, bool> ConfirmDecision { get; set; } =
        ConfirmWithDialog;

    public IReadOnlyList<PanelItemPresentation> ApprovalRows
    {
        get => _approvalRows;
        private set
        {
            _approvalRows = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(ApprovalRows)));
        }
    }

    public IReadOnlyList<PanelItemPresentation> DecidedApprovalRows
    {
        get => _decidedApprovalRows;
        private set
        {
            _decidedApprovalRows = value;
            PropertyChanged?.Invoke(
                this,
                new PropertyChangedEventArgs(nameof(DecidedApprovalRows)));
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

    private static void OpenFileClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (sender is Button { DataContext: PanelItemPresentation card }
            && card.Destination is { Length: > 0 } destination)
        {
            _ = Process.Start(new ProcessStartInfo(destination)
            {
                UseShellExecute = true,
            });
        }
    }

    private static void OpenFolderClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (sender is Button { DataContext: PanelItemPresentation card }
            && card.Destination is { Length: > 0 } destination
            && Path.GetDirectoryName(destination) is { Length: > 0 } directory)
        {
            _ = Process.Start(new ProcessStartInfo(directory)
            {
                UseShellExecute = true,
            });
        }
    }

    private async void RollbackClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (_coordinator is not null
            && sender is Button { DataContext: PanelItemPresentation card }
            && card.ReceiptRef is { Length: > 0 } receiptRef)
        {
            await _coordinator.RequestOfficeRollbackAsync(
                new OfficeRollbackRequestIntent(receiptRef),
                CancellationToken.None);
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

    private static bool ConfirmWithDialog(
        PanelItemPresentation card,
        ApprovalDecision decision)
    {
        var action = decision == ApprovalDecision.Approve ? "approve" : "reject";
        var result = MessageBox.Show(
            ConfirmationMessage(card, action),
            "Confirm approval decision",
            MessageBoxButton.YesNo,
            decision == ApprovalDecision.Approve
                ? MessageBoxImage.Warning
                : MessageBoxImage.Question);
        return result == MessageBoxResult.Yes;
    }

    internal static string ConfirmationMessage(
        PanelItemPresentation card,
        string action) =>
        $"Confirm {action}?\n\n"
        + $"{card.Summary}\n"
        + $"{card.Destination ?? "No destination"}\n"
        + card.OverwriteLabel;

    private void ModelPropertyChanged(object? sender, PropertyChangedEventArgs eventArgs)
    {
        if (eventArgs.PropertyName == nameof(ShellPresentationModel.Workspace))
        {
            UpdateRows();
        }
    }

    private void UpdateRows()
    {
        var rows = _model?.Workspace?.ApprovalRequests
            .Where(row =>
                string.Equals(row.Kind, "approval", StringComparison.Ordinal))
            .ToArray() ?? [];
        ApprovalRows = rows.Where(row => !row.Decided).ToArray();
        DecidedApprovalRows = rows.Where(row => row.Decided).ToArray();
    }

    private void ViewUnloaded(object sender, RoutedEventArgs eventArgs)
    {
        if (_model is not null)
        {
            _model.PropertyChanged -= ModelPropertyChanged;
        }
    }
}
