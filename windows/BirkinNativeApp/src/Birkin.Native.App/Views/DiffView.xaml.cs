using System.ComponentModel;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class DiffView : UserControl, INotifyPropertyChanged
{
    private readonly ShellPresentationModel? _model;
    private readonly NativeProjectionStore? _projectionStore;
    private PanelItemPresentation? _canonicalDiff;
    private IReadOnlyList<PanelItemPresentation> _diffRows = [];

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
    public IReadOnlyList<PanelItemPresentation> DiffRows
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
        if (envelope.Kind != NativeMessageKind.Event
            || envelope.Body["type"] is not NativeJsonString { Value: "office.diff_ready" }
            || envelope.Body["payload"] is not NativeJsonObject payload
            || payload["result"] is not NativeJsonObject result
            || result["diff"] is not NativeJsonObject diff
            || diff["diff_id"] is not NativeJsonString diffId)
        {
            return;
        }

        var summary = Encoding.UTF8.GetString(NativeJsonSerializer.Serialize(diff));
        _ = Dispatcher.BeginInvoke(() =>
        {
            _canonicalDiff = new PanelItemPresentation(diffId.Value, "diff", summary);
            UpdateRows();
        });
    }

    private void UpdateRows()
    {
        var projected = _model?.Workspace?.Office
            .Where(row => string.Equals(row.Kind, "diff", StringComparison.Ordinal)) ?? [];
        DiffRows = _canonicalDiff is null ? projected.ToArray() : [.. projected, _canonicalDiff];
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
