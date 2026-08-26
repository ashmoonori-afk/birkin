using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class ApprovalView : UserControl, INotifyPropertyChanged
{
    private readonly ShellPresentationModel? _model;
    private readonly ShellCoordinator? _coordinator;
    private readonly Dictionary<string, ConversationRowPresentation> _canonicalApprovals = new(StringComparer.Ordinal);
    private IReadOnlyList<ConversationRowPresentation> _approvalRows = [];

    public ApprovalView() => InitializeComponent();

    public ApprovalView(ShellPresentationModel model, ShellCoordinator coordinator) : this()
    {
        _model = model;
        _coordinator = coordinator;
        DataContext = model;
        model.PropertyChanged += ModelPropertyChanged;
        coordinator.ProjectionStore.CanonicalApplied += CanonicalApplied;
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

    private void CanonicalApplied(NativeEnvelope envelope)
    {
        if (envelope.Kind != NativeMessageKind.Event
            || envelope.Body["type"] is not NativeJsonString type
            || envelope.Body["payload"] is not NativeJsonObject payload
            || payload["approval_id"] is not NativeJsonString approvalId)
        {
            return;
        }

        if (type.Value == "approval.requested")
        {
            var summary = payload["summary"] is NativeJsonString text ? text.Value : "Approval required";
            var cursor = envelope.Body["cursor"] is NativeJsonInteger value ? value.Value : 0;
            _ = Dispatcher.BeginInvoke(() =>
            {
                _canonicalApprovals[approvalId.Value] = new ConversationRowPresentation(
                    approvalId.Value, "approval", summary, "python:authority", cursor);
                UpdateRows();
            });
        }
        else if (type.Value == "approval.answered")
        {
            _ = Dispatcher.BeginInvoke(() =>
            {
                _ = _canonicalApprovals.Remove(approvalId.Value);
                UpdateRows();
            });
        }
    }

    private void UpdateRows()
    {
        var projected = _model?.Workspace?.Conversation
            .Where(row => string.Equals(row.Kind, "approval", StringComparison.Ordinal)) ?? [];
        ApprovalRows = [.. projected, .. _canonicalApprovals.Values];
    }

    private void ViewUnloaded(object sender, RoutedEventArgs eventArgs)
    {
        if (_model is not null)
        {
            _model.PropertyChanged -= ModelPropertyChanged;
        }
        if (_coordinator is not null)
        {
            _coordinator.ProjectionStore.CanonicalApplied -= CanonicalApplied;
        }
    }
}
