using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class OfficeView : UserControl, INotifyPropertyChanged
{
    private readonly ShellPresentationModel? _model;
    private readonly ShellCoordinator? _coordinator;
    private readonly Dictionary<string, PanelItemPresentation> _canonicalDocuments = new(StringComparer.Ordinal);
    private IReadOnlyList<PanelItemPresentation> _documentRows = [];

    public OfficeView()
    {
        InitializeComponent();
        ImportHost.Content = new ImportView();
        DiffHost.Content = new DiffView();
    }

    public OfficeView(ShellPresentationModel model, ShellCoordinator coordinator) : this()
    {
        _model = model;
        _coordinator = coordinator;
        DataContext = model;
        ImportHost.Content = new ImportView(model, coordinator);
        DiffHost.Content = new DiffView(model, coordinator.ProjectionStore);
        model.PropertyChanged += ModelPropertyChanged;
        coordinator.ProjectionStore.CanonicalApplied += CanonicalApplied;
        UpdateRows();
        Unloaded += ViewUnloaded;
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    public IReadOnlyList<PanelItemPresentation> DocumentRows
    {
        get => _documentRows;
        private set
        {
            _documentRows = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(DocumentRows)));
        }
    }

    private async void CreateClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (_coordinator is not null && OutputNameBox.Text.Length > 0 && ContentBox.Text.Length > 0)
        {
            await _coordinator.CreateOfficeDocumentAsync(
                new OfficeCreateIntent("docx", new OfficeDocumentContent([ContentBox.Text]), OutputNameBox.Text),
                CancellationToken.None);
        }
    }

    private async void SelectClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (_coordinator is not null && sender is Button { Tag: string artifactId })
        {
            await _coordinator.SelectOfficeDocumentAsync(
                new OfficeSelectIntent(artifactId),
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
            || envelope.Body["type"] is not NativeJsonString { Value: "office.updated" }
            || envelope.Body["payload"] is not NativeJsonObject payload
            || payload["result"] is not NativeJsonObject result
            || result["artifact"] is not NativeJsonObject artifact
            || artifact["artifact_id"] is not NativeJsonString artifactId)
        {
            return;
        }

        var mediaType = artifact["media_type"] is NativeJsonString value ? value.Value : "office";
        _ = Dispatcher.BeginInvoke(() =>
        {
            _canonicalDocuments[artifactId.Value] = new PanelItemPresentation(
                artifactId.Value, "document", $"{mediaType}  {artifactId.Value}");
            UpdateRows();
        });
    }

    private void UpdateRows()
    {
        var projected = _model?.Workspace?.Office
            .Where(row => !string.Equals(row.Kind, "diff", StringComparison.Ordinal)) ?? [];
        DocumentRows = [.. projected, .. _canonicalDocuments.Values];
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
