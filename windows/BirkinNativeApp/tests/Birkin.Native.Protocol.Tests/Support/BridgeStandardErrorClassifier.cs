using System.Text.RegularExpressions;

namespace Birkin.Native.Protocol.Tests.Support;

internal static partial class BridgeStandardErrorClassifier
{
    internal static BridgeStandardErrorClassification Classify(string standardError)
    {
        if (string.IsNullOrEmpty(standardError))
        {
            return new(string.Empty, string.Empty);
        }

        var runtimeDiagnostics = new List<string>();
        var unexpected = new List<string>();
        var lines = standardError.Replace("\r\n", "\n", StringComparison.Ordinal).Split('\n');
        var lineCount = lines.Length;
        if (lines[^1].Length == 0)
        {
            lineCount--;
        }

        for (var index = 0; index < lineCount; index++)
        {
            var header = PywinautoInvalidEscapeWarning().Match(lines[index]);
            if (header.Success
                && index + 1 < lineCount
                && IsWarningSourceContinuation(lines[index + 1], header.Groups["escape"].Value))
            {
                runtimeDiagnostics.Add(lines[index]);
                runtimeDiagnostics.Add(lines[++index]);
                continue;
            }

            unexpected.Add(lines[index]);
        }

        return new(
            string.Join(Environment.NewLine, runtimeDiagnostics),
            string.Join(Environment.NewLine, unexpected));
    }

    private static bool IsWarningSourceContinuation(string line, string escape) =>
        line.StartsWith("  ", StringComparison.Ordinal)
        && line.Length > 2
        && line[2] != ' '
        && line.Contains(escape, StringComparison.Ordinal);

    [GeneratedRegex(
        @"^(?:(?:[A-Za-z]:)?[^:\r\n]*[\\/])?\.venv[\\/](?:Lib|lib)[\\/]site-packages[\\/]pywinauto[\\/][^:\r\n]+\.py:\d+: SyntaxWarning: invalid escape sequence '(?<escape>\\[^'\r\n])'$",
        RegexOptions.CultureInvariant)]
    private static partial Regex PywinautoInvalidEscapeWarning();
}

internal sealed record BridgeStandardErrorClassification(
    string RuntimeDiagnostics,
    string UnexpectedStandardError);
