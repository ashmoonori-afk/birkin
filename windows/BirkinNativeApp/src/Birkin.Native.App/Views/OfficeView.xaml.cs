using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class OfficeView : UserControl, INotifyPropertyChanged
{
    private readonly ShellPresentationModel? _model;
    private readonly ShellCoordinator? _coordinator;
    private readonly Dictionary<string, OfficeDocumentRowPresentation> _canonicalDocuments = new(StringComparer.Ordinal);
    private IReadOnlyList<OfficeDocumentRowPresentation> _documentRows = [];

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
    public IReadOnlyList<OfficeDocumentRowPresentation> DocumentRows
    {
        get => _documentRows;
        private set
        {
            _documentRows = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(DocumentRows)));
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
        if (OfficeDocumentPresentationMapper.FromCanonical(envelope) is not { } document)
        {
            return;
        }

        _ = Dispatcher.BeginInvoke(() =>
        {
            _canonicalDocuments[document.Id] = document;
            UpdateRows();
        });
    }

    private void UpdateRows()
    {
        var projected = (_model?.Workspace?.Office
            .Where(row => !string.Equals(row.Kind, "diff", StringComparison.Ordinal)) ?? [])
            .Select(OfficeDocumentPresentationMapper.FromProjected);
        DocumentRows = projected
            .Concat(_canonicalDocuments.Values)
            .GroupBy(row => row.Id, StringComparer.Ordinal)
            .Select(group => group.Last())
            .ToArray();
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

    internal Task<bool> ImportDroppedFilesAsync(
        IReadOnlyList<string> paths)
    {
        ImportPanel.IsExpanded = true;
        return ((ImportView)ImportHost.Content).ImportDroppedFilesAsync(paths);
    }

    internal void ReportImportSelectionError()
    {
        ImportPanel.IsExpanded = true;
        ((ImportView)ImportHost.Content).ReportImportSelectionError();
    }
}
