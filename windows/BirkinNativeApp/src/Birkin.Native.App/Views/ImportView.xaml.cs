using System.ComponentModel;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;
using System.Windows.Media;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class ImportView : UserControl
{
    private readonly ShellCoordinator? _coordinator;
    private readonly ShellPresentationModel? _model;
    private readonly IOfficeFilePicker _picker;
    private IReadOnlyList<string> _selectedPaths = [];
    private bool _importPending;
    private bool _subscribed;

    public ImportView()
    {
        _picker = new OfficeFilePicker();
        InitializeComponent();
    }

    internal ImportView(
        ShellPresentationModel model,
        ShellCoordinator coordinator,
        IOfficeFilePicker? picker = null)
        : this()
    {
        _coordinator = coordinator;
        _model = model;
        _picker = picker ?? _picker;
        DataContext = model;
        SubscribeModel();
        Loaded += ViewLoaded;
        Unloaded += ViewUnloaded;
    }

    private void BrowseClicked(object sender, RoutedEventArgs eventArgs)
    {
        var returnFocus = Keyboard.FocusedElement;
        try
        {
            if (_picker.SelectOfficeFiles(Window.GetWindow(this)) is { Count: > 0 } selected)
            {
                _selectedPaths = selected;
                PathBox.Text = selected.Count == 1
                    ? selected[0]
                    : $"{selected.Count}개 파일 선택됨";
                _importPending = false;
                HideStatus();
            }
        }
        finally
        {
            _ = Dispatcher.BeginInvoke(
                DispatcherPriority.Input,
                new Action(() => _ = returnFocus?.Focus()));
        }
    }

    private async void ImportClicked(object sender, RoutedEventArgs eventArgs)
    {
        _ = await ImportSelectedAsync();
    }

    internal async Task<bool> ImportDroppedFilesAsync(
        IReadOnlyList<string> paths)
    {
        if (paths.Count == 0)
        {
            ReportImportSelectionError();
            return false;
        }
        _selectedPaths = paths;
        PathBox.Text = paths.Count == 1 ? paths[0] : $"{paths.Count}개 파일 선택됨";
        return await ImportSelectedAsync();
    }

    internal void ReportImportSelectionError() =>
        ShowStatus(
            "지원하는 파일을 창으로 끌어오거나 찾아보기에서 선택하세요.",
            "DangerBrush");

    private async Task<bool> ImportSelectedAsync()
    {
        var paths = _selectedPaths.Count > 0
            ? _selectedPaths
            : PathBox.Text.Length > 0
                ? [PathBox.Text]
                : [];
        if (_coordinator is null || paths.Count == 0)
        {
            ReportImportSelectionError();
            return false;
        }
        var succeeded = 0;
        var failed = new List<string>();
        foreach (var path in paths)
        {
            if (!OfficeFileSelection.IsSupported(path))
            {
                failed.Add(Path.GetFileName(path));
                continue;
            }
            PathBox.Text = path;
            ShowStatus("파일을 안전한 작업공간으로 가져오는 중입니다.", "MutedBrush");
            _importPending = true;
            if (await _coordinator.ImportAsync(
                    new FileImportIntent(path),
                    CancellationToken.None))
            {
                succeeded++;
            }
            else
            {
                failed.Add(Path.GetFileName(path));
            }
        }
        _selectedPaths = [];
        PresentWorkflow();
        if (failed.Count > 0)
        {
            ShowStatus(
                $"{succeeded}개를 가져왔습니다. 실패: {string.Join(", ", failed)}",
                "DangerBrush");
        }
        else if (succeeded > 1)
        {
            ShowStatus($"파일 {succeeded}개를 가져왔습니다.", "SuccessBrush");
        }
        return succeeded > 0;
    }

    private void ModelPropertyChanged(
        object? sender,
        PropertyChangedEventArgs eventArgs)
    {
        if (eventArgs.PropertyName
            == nameof(ShellPresentationModel.OfficeWorkflow))
        {
            PresentWorkflow();
        }
    }

    private void PresentWorkflow()
    {
        var workflow = _model?.OfficeWorkflow;
        if (workflow is null)
        {
            return;
        }
        if (!string.Equals(
                workflow.CommandType,
                ImportCommands.CommandType,
                StringComparison.Ordinal))
        {
            if (_importPending
                && !workflow.Availability.FileImport.IsEnabled)
            {
                _importPending = false;
                ShowStatus(
                    ImportRefusalText.FromCode(
                        workflow.Availability.FileImport.DisabledReason),
                    "DangerBrush");
            }
            return;
        }
        switch (workflow.CommandState)
        {
            case WorkflowCommandState.PendingReceipt:
                _importPending = true;
                ShowStatus(
                    "파일을 안전한 작업공간으로 가져오는 중입니다.",
                    "MutedBrush");
                break;
            case WorkflowCommandState.AcceptedPendingProjection:
                _importPending = false;
                ShowStatus(
                    "파일을 가져왔습니다. 아래 파일을 첫 보고서 요청에 사용할 수 있습니다.",
                    "SuccessBrush");
                break;
            case WorkflowCommandState.Refused:
                _importPending = false;
                ShowStatus(
                    ImportRefusalText.FromCode(workflow.RefusalCode),
                    "DangerBrush");
                break;
            case WorkflowCommandState.Idle:
                break;
            default:
                throw new InvalidOperationException(
                    "Unknown file import command state.");
        }
    }

    private void ShowStatus(string text, string brushKey)
    {
        StatusText.Text = text;
        StatusText.Foreground = (Brush)FindResource(brushKey);
        StatusText.Visibility = Visibility.Visible;
    }

    private void HideStatus()
    {
        StatusText.Text = string.Empty;
        StatusText.Visibility = Visibility.Collapsed;
    }

    private void ViewUnloaded(object sender, RoutedEventArgs eventArgs)
    {
        if (_model is not null && _subscribed)
        {
            _model.PropertyChanged -= ModelPropertyChanged;
            _subscribed = false;
        }
    }

    private void ViewLoaded(object sender, RoutedEventArgs eventArgs) =>
        SubscribeModel();

    private void SubscribeModel()
    {
        if (_model is not null && !_subscribed)
        {
            _model.PropertyChanged += ModelPropertyChanged;
            _subscribed = true;
        }
    }
}
