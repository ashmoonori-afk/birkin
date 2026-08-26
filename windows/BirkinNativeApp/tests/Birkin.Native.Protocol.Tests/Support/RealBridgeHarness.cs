using System.Diagnostics;
using Birkin.Native.Protocol.Transport;

namespace Birkin.Native.Protocol.Tests.Support;

internal sealed class RealBridgeHarness : IAsyncDisposable
{
    private readonly Process _process;
    private readonly Task<string> _standardError;

    private RealBridgeHarness(Process process, string temporaryRoot, Task<string> standardError)
    {
        _process = process;
        TemporaryRoot = temporaryRoot;
        _standardError = standardError;
    }

    public string TemporaryRoot { get; }

    public string BridgeRoot => Path.Combine(TemporaryRoot, "bridge");

    public static async Task<(RealBridgeHarness Harness, BridgeAnnouncement Announcement)> StartAsync(
        CancellationToken cancellationToken)
    {
        var temporaryRoot = Path.Combine(Path.GetTempPath(), $"birkin-w5-bridge-{Guid.NewGuid():N}");
        var bridgeRoot = Path.Combine(temporaryRoot, "bridge");
        Directory.CreateDirectory(bridgeRoot);
        var start = CreateStartInfo(temporaryRoot, bridgeRoot);

        var process = new Process { StartInfo = start };
        try
        {
            if (!process.Start())
            {
                throw new InvalidOperationException("repository Python did not start the native bridge");
            }

            var standardError = process.StandardError.ReadToEndAsync(cancellationToken);
            string? line;
            do
            {
                line = await process.StandardOutput.ReadLineAsync(cancellationToken);
                if (line is null)
                {
                    throw new InvalidOperationException(
                        $"bridge exited before announcing its endpoint with code {process.ExitCode}");
                }
            }
            while (!line.Contains("\"event\":\"listening\"", StringComparison.Ordinal));

            var harness = new RealBridgeHarness(process, temporaryRoot, standardError);
            return (harness, BridgeAnnouncement.Parse(line));
        }
        catch
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
                await process.WaitForExitAsync(CancellationToken.None);
            }
            process.Dispose();
            Directory.Delete(temporaryRoot, recursive: true);
            throw;
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (!_process.HasExited)
        {
            _process.Kill(entireProcessTree: true);
        }
        await _process.WaitForExitAsync(CancellationToken.None);
        var standardError = await _standardError;
        _process.Dispose();
        Directory.Delete(TemporaryRoot, recursive: true);
        ValidateStandardError(standardError);
    }

    public static string RepositoryRoot => FindRepositoryRoot();

    internal static ProcessStartInfo CreateStartInfo(string temporaryRoot, string bridgeRoot)
    {
        var repositoryRoot = FindRepositoryRoot();
        var start = new ProcessStartInfo
        {
            FileName = FindRepositoryPython(repositoryRoot),
            WorkingDirectory = repositoryRoot,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };
        start.Environment["BIRKIN_HOME"] = Path.Combine(temporaryRoot, "home");
        foreach (var argument in new[]
        {
            "-m", "birkin.native.serve",
            "--transport", "loopback", "--root", bridgeRoot,
        })
        {
            start.ArgumentList.Add(argument);
        }
        return start;
    }

    internal static void ValidateStandardError(string standardError)
    {
        var classified = BridgeStandardErrorClassifier.Classify(standardError);
        if (!string.IsNullOrEmpty(classified.UnexpectedStandardError))
        {
            throw new InvalidOperationException(
                $"native bridge wrote stderr: {classified.UnexpectedStandardError}");
        }
    }

    private static string FindRepositoryPython(string repositoryRoot)
    {
        var relativePath = OperatingSystem.IsWindows()
            ? Path.Combine(".venv", "Scripts", "python.exe")
            : Path.Combine(".venv", "bin", "python");
        var executable = Path.Combine(repositoryRoot, relativePath);
        return File.Exists(executable)
            ? executable
            : throw new InvalidOperationException($"locked repository Python was not found: {executable}");
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "pyproject.toml")))
        {
            directory = directory.Parent;
        }
        return directory?.FullName
            ?? throw new InvalidOperationException("repository root was not found");
    }
}
