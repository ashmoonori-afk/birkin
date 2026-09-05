using Microsoft.Win32;
using System.IO;
using System.Windows;

namespace Birkin.Native.App.Views;

internal interface IOfficeFilePicker
{
    IReadOnlyList<string> SelectOfficeFiles(Window? owner);
}

internal sealed class OfficeFilePicker : IOfficeFilePicker
{
    internal const string FileFilter =
        "지원 문서|*.docx;*.xlsx;*.pptx;*.pdf;*.hwpx;*.txt"
        + "|Word 문서|*.docx"
        + "|Excel 통합 문서|*.xlsx"
        + "|PowerPoint 프레젠테이션|*.pptx"
        + "|PDF 문서|*.pdf"
        + "|한글 HWPX 문서|*.hwpx"
        + "|텍스트 문서|*.txt";
    internal const string DialogTitle = "가져올 업무 문서 선택";

    public IReadOnlyList<string> SelectOfficeFiles(Window? owner)
    {
        var dialog = new OpenFileDialog
        {
            CheckFileExists = true,
            Filter = FileFilter,
            Multiselect = true,
            Title = DialogTitle,
        };
        return dialog.ShowDialog(owner) is true ? dialog.FileNames : [];
    }
}

internal static class OfficeFileSelection
{
    private static readonly IReadOnlySet<string> SupportedExtensions =
        new HashSet<string>(
            [".docx", ".xlsx", ".pptx", ".pdf", ".hwpx", ".txt"],
            StringComparer.OrdinalIgnoreCase);

    public static bool IsSupported(string path) =>
        !string.IsNullOrWhiteSpace(path)
        && SupportedExtensions.Contains(Path.GetExtension(path));
}

internal static class ImportRefusalText
{
    public static string FromCode(string? code) => code switch
    {
        "E_BODY" =>
            "파일을 가져오지 못했습니다. 경로, 파일 크기 또는 파일 상태를 확인하세요.",
        "E_STALE_CURSOR" =>
            "작업 상태가 바뀌었습니다. 파일 가져오기를 다시 시도하세요.",
        "E_UNSUPPORTED_COMMAND" or "E_COMMAND_UNADVERTISED" =>
            "현재 Birkin 연결은 파일 가져오기를 지원하지 않습니다.",
        "E_CONNECTION_NOT_READY" =>
            "Birkin 연결이 준비된 뒤 파일 가져오기를 다시 시도하세요.",
        "E_CAPABILITY_EXPIRED" =>
            "연결 권한이 만료되었습니다. 다시 연결한 뒤 시도하세요.",
        "E_PROJECTION_FORBIDS_MUTATION" =>
            "현재 작업 상태에서는 파일을 가져올 수 없습니다.",
        { Length: > 0 } value =>
            $"파일을 가져오지 못했습니다. 오류 코드: {value}",
        _ => "파일을 가져오지 못했습니다. 잠시 후 다시 시도하세요.",
    };
}
