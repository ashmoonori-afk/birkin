using System.ComponentModel;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
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
    private IReadOnlyList<OfficeFormatSupportPresentation> _supportRows = [];

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
        UpdateSupportRows();
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
    public IReadOnlyList<OfficeFormatSupportPresentation> SupportRows
    {
        get => _supportRows;
        private set
        {
            _supportRows = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(SupportRows)));
        }
    }

    private async void DraftClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (_coordinator is null)
        {
            return;
        }
        var purpose = PurposeBox.Text.Trim();
        var destination = DestinationBox.Text.Trim();
        var paragraphs = ContentBox.Text
            .Split(["\r\n", "\n"], StringSplitOptions.None)
            .Where(paragraph => !string.IsNullOrWhiteSpace(paragraph))
            .ToArray();
        if (purpose.Length == 0 || paragraphs.Length == 0 || destination.Length == 0)
        {
            ShowRequestStatus("목적, 본문, 저장 위치를 모두 입력하세요.", "DangerBrush");
            return;
        }
        if (!string.Equals(Path.GetExtension(destination), ".docx", StringComparison.OrdinalIgnoreCase))
        {
            ShowRequestStatus("현재 새 문서 저장은 DOCX만 지원합니다.", "DangerBrush");
            return;
        }

        var submitted = await _coordinator.DraftOfficeDocumentAsync(
            new OfficeDraftIntent(
                purpose,
                "docx",
                new OfficeDocumentContent(paragraphs),
                purpose,
                destination,
                OverwriteBox.IsChecked is true),
            CancellationToken.None);
        ShowRequestStatus(
            submitted
                ? "초안을 검토 요청했습니다. 승인 화면에서 내용과 저장 위치를 확인하세요."
                : "초안 요청을 보내지 못했습니다. 연결 상태와 위 오류를 확인하세요.",
            submitted ? "SuccessBrush" : "DangerBrush");
    }

    private void EditDraftClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (_coordinator is null)
        {
            return;
        }
        var purpose = PurposeBox.Text.Trim();
        var destination = DestinationBox.Text.Trim();
        if (purpose.Length == 0)
        {
            ShowRequestStatus("수정할 내용을 목적에 입력하세요.", "DangerBrush");
            return;
        }
        var destinationText = destination.Length > 0
            ? $" 결과는 '{destination}'에 저장해 주세요."
            : string.Empty;
        _coordinator.SetConversationDraft(
            $"선택한 첨부 문서를 다음과 같이 수정해 주세요: {purpose}.{destinationText}");
        ShowRequestStatus(
            "수정 요청을 대화 입력창에 작성했습니다. 첨부와 내용을 확인한 뒤 보내세요.",
            "SuccessBrush");
    }

    private void ShowRequestStatus(string text, string brushKey)
    {
        RequestStatusText.Text = text;
        RequestStatusText.Foreground = (Brush)FindResource(brushKey);
        RequestStatusText.Visibility = Visibility.Visible;
    }

    private void ModelPropertyChanged(object? sender, PropertyChangedEventArgs eventArgs)
    {
        if (eventArgs.PropertyName == nameof(ShellPresentationModel.Workspace))
        {
            UpdateRows();
        }
        else if (eventArgs.PropertyName == nameof(ShellPresentationModel.OfficeWorkflow)
            && string.Equals(
                _model?.OfficeWorkflow.CommandType,
                OfficeCommands.DraftCommandType,
                StringComparison.Ordinal)
            && _model?.OfficeWorkflow.RefusalText is { } refusal)
        {
            ShowRequestStatus(refusal, "DangerBrush");
        }
    }

    private void CanonicalApplied(NativeEnvelope envelope)
    {
        if ((envelope.Kind == NativeMessageKind.SurfaceSnapshot
                || envelope.Kind == NativeMessageKind.SurfaceEvent)
            && envelope.Body["surface"] is NativeJsonString { Value: "office" })
        {
            _ = Dispatcher.BeginInvoke(UpdateSupportRows);
        }
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

    private void UpdateSupportRows() => SupportRows =
        OfficeSupportPresentationMapper.FromSurface(
            _coordinator?.ProjectionStore.Surface("office"));

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
