using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class DiffView : UserControl, INotifyPropertyChanged
{
    private readonly ShellPresentationModel? _model;
    private readonly NativeProjectionStore? _projectionStore;
    private OfficeDiffPresentation? _canonicalDiff;
    private IReadOnlyList<OfficeDiffRowPresentation> _diffRows = [];

    public DiffView()
    {
        InitializeComponent();
        Visibility = System.Windows.Visibility.Collapsed;
    }

    public DiffView(ShellPresentationModel model) : this(model, null)
    {
    }

    public DiffView(ShellPresentationModel model, NativeProjectionStore? projectionStore) : this()
    {
        _model = model;
        _projectionStore = projectionStore;
        DataContext = model;
        model.PropertyChanged += ModelPropertyChanged;
        if (_projectionStore is not null)
        {
            _projectionStore.CanonicalApplied += CanonicalApplied;
        }
        UpdateRows();
        Unloaded += ViewUnloaded;
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public string ApprovalStateText => _canonicalDiff?.ApprovalState == OfficeDiffApprovalState.Approved
        ? "APPROVED"
        : "BEFORE APPROVAL";

    public IReadOnlyList<OfficeDiffRowPresentation> DiffRows
    {
        get => _diffRows;
        private set
        {
            _diffRows = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(DiffRows)));
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
        if (_canonicalDiff is { } current)
        {
            var updated = OfficeDiffPresentationMapper.ApplyApprovalReceipt(
                current,
                envelope);
            if (updated.ApprovalState != current.ApprovalState)
            {
                _ = Dispatcher.BeginInvoke(() =>
                {
                    _canonicalDiff = updated;
                    PropertyChanged?.Invoke(
                        this,
                        new PropertyChangedEventArgs(nameof(ApprovalStateText)));
                });
                return;
            }
        }

        if (OfficeDiffPresentationMapper.FromCanonical(envelope) is not { } presentation)
        {
            return;
        }

        _ = Dispatcher.BeginInvoke(() =>
        {
            _canonicalDiff = presentation;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(ApprovalStateText)));
            UpdateRows();
        });
    }

    private void UpdateRows()
    {
        var projected = _model?.Workspace?.Office
            .Where(row => string.Equals(row.Kind, "diff", StringComparison.Ordinal))
            .Select(OfficeDiffPresentationMapper.FromProjected) ?? [];
        DiffRows = _canonicalDiff?.Rows ?? projected.ToArray();
        Visibility = DiffRows.Count == 0 ? Visibility.Collapsed : Visibility.Visible;
    }

    private void ViewUnloaded(object sender, RoutedEventArgs eventArgs)
    {
        if (_model is not null)
        {
            _model.PropertyChanged -= ModelPropertyChanged;
        }
        if (_projectionStore is not null)
        {
            _projectionStore.CanonicalApplied -= CanonicalApplied;
        }
    }
}
