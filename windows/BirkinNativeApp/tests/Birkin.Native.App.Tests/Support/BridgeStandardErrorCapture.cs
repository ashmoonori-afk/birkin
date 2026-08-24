using System.Text.RegularExpressions;
using Birkin.Native.Protocol.Tests.Support;

namespace Birkin.Native.App.Tests.Support;

internal sealed class BridgeStandardErrorCapture
{
    private static readonly Regex BuildProgress = new(
        @"^[ ]*(?:Building|Built) [A-Za-z0-9][A-Za-z0-9._-]* @ file:///.+$",
        RegexOptions.CultureInvariant);
    private static readonly Regex EnvironmentProgress = new(
        @"^[ ]*(?:Uninstalled|Installed|Resolved|Audited) \d+ packages? in \d+(?:\.\d+)?(?:ms|s)$",
        RegexOptions.CultureInvariant);

    private readonly object _gate = new();
    private readonly List<string> _bridgeStandardError = [];
    private readonly List<string> _launcherDiagnostics = [];

    public string StandardError
    {
        get
        {
            lock (_gate)
            {
                return BridgeStandardErrorClassifier
                    .Classify(string.Join(Environment.NewLine, _bridgeStandardError))
                    .UnexpectedStandardError;
            }
        }
    }

    public string LauncherDiagnostics
    {
        get
        {
            lock (_gate)
            {
                var runtimeDiagnostics = BridgeStandardErrorClassifier
                    .Classify(string.Join(Environment.NewLine, _bridgeStandardError))
                    .RuntimeDiagnostics;
                return string.Join(
                    Environment.NewLine,
                    _launcherDiagnostics.Append(runtimeDiagnostics)
                        .Where(diagnostic => !string.IsNullOrEmpty(diagnostic)));
            }
        }
    }

    public void Append(string line)
    {
        lock (_gate)
        {
            // The auto-bump hook changes pyproject.toml on every commit, so uv may rebuild and report launcher progress on STDERR.
            if (BuildProgress.IsMatch(line) || EnvironmentProgress.IsMatch(line))
            {
                _launcherDiagnostics.Add(line);
                return;
            }

            _bridgeStandardError.Add(line);
        }
    }
}
