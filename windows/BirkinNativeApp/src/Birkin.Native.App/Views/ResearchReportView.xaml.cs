using System.ComponentModel;
using System.Diagnostics;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Documents;
using System.Windows.Navigation;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class ResearchReportView
{
    private static readonly Regex HttpUrl = new(
        @"https?://[^\s<>\]\)]+",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    private ShellPresentationModel? _model;

    public ResearchReportView()
    {
        InitializeComponent();
        DataContextChanged += (_, _) => AttachModel(DataContext as ShellPresentationModel);
    }

    private void AttachModel(ShellPresentationModel? model)
    {
        if (_model is not null)
            _model.PropertyChanged -= ModelPropertyChanged;
        _model = model;
        if (_model is not null)
            _model.PropertyChanged += ModelPropertyChanged;
        RenderReport();
    }

    private void ModelPropertyChanged(object? sender, PropertyChangedEventArgs args)
    {
        if (args.PropertyName == nameof(ShellPresentationModel.Workspace))
            RenderReport();
    }

    private void RenderReport()
    {
        var text = _model?.Workspace?.Conversation
            .LastOrDefault(row => string.Equals(
                row.Kind, "assistant_message", StringComparison.Ordinal))?.Text;
        Report.Document.Blocks.Clear();
        EmptyState.Visibility = string.IsNullOrWhiteSpace(text)
            ? Visibility.Visible
            : Visibility.Collapsed;
        if (string.IsNullOrWhiteSpace(text))
            return;

        foreach (var rawLine in text.Replace("\r\n", "\n", StringComparison.Ordinal).Split('\n'))
        {
            var line = rawLine.TrimEnd();
            var paragraph = new Paragraph { Margin = new Thickness(0, 0, 0, 8) };
            if (line.StartsWith("### ", StringComparison.Ordinal))
            {
                paragraph.FontSize = 17;
                paragraph.FontWeight = FontWeights.SemiBold;
                line = line[4..];
            }
            else if (line.StartsWith("## ", StringComparison.Ordinal))
            {
                paragraph.FontSize = 20;
                paragraph.FontWeight = FontWeights.SemiBold;
                paragraph.Margin = new Thickness(0, 12, 0, 8);
                line = line[3..];
            }
            else if (line.StartsWith("# ", StringComparison.Ordinal))
            {
                paragraph.FontSize = 24;
                paragraph.FontWeight = FontWeights.SemiBold;
                paragraph.Margin = new Thickness(0, 4, 0, 12);
                line = line[2..];
            }
            else if (line.StartsWith("- ", StringComparison.Ordinal))
            {
                paragraph.TextIndent = -16;
                paragraph.Margin = new Thickness(16, 0, 0, 6);
                line = $"• {line[2..]}";
            }
            else if (line.StartsWith("> ", StringComparison.Ordinal))
            {
                paragraph.FontStyle = FontStyles.Italic;
                paragraph.Padding = new Thickness(12, 6, 8, 6);
                paragraph.BorderThickness = new Thickness(3, 0, 0, 0);
                paragraph.BorderBrush = (System.Windows.Media.Brush)FindResource("AccentBrush");
                line = line[2..];
            }
            AddTextAndLinks(paragraph, line);
            Report.Document.Blocks.Add(paragraph);
        }
    }

    private void AddTextAndLinks(Paragraph paragraph, string line)
    {
        var offset = 0;
        foreach (Match match in HttpUrl.Matches(line))
        {
            paragraph.Inlines.Add(new Run(line[offset..match.Index]));
            if (Uri.TryCreate(match.Value, UriKind.Absolute, out var uri)
                && uri.Scheme is "http" or "https")
            {
                var link = new Hyperlink(new Run(match.Value)) { NavigateUri = uri };
                link.RequestNavigate += OpenLink;
                paragraph.Inlines.Add(link);
            }
            else
            {
                paragraph.Inlines.Add(new Run(match.Value));
            }
            offset = match.Index + match.Length;
        }
        paragraph.Inlines.Add(new Run(line[offset..]));
    }

    private void OpenLink(object sender, RequestNavigateEventArgs args)
    {
        if (args.Uri.Scheme is not ("http" or "https"))
            return;
        try
        {
            _ = Process.Start(new ProcessStartInfo(args.Uri.AbsoluteUri) { UseShellExecute = true });
        }
        catch (Exception exception) when (
            exception is System.ComponentModel.Win32Exception
                or InvalidOperationException)
        {
            Report.ToolTip = "링크를 열 수 없습니다. 주소를 복사해 다시 시도해 주세요.";
        }
        args.Handled = true;
    }
}
