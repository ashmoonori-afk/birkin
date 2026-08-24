using System.Diagnostics;
using System.IO;

namespace Birkin.Native.App.Tests.Support;

internal sealed class BridgeProcessHarness : IAsyncDisposable
{
    private readonly Process _process;
    private readonly TaskCompletionSource<string> _listening;
    private readonly BridgeStandardErrorCapture _standardError;

    private BridgeProcessHarness(
        Process process,
        string temporaryRoot,
        TaskCompletionSource<string> listening,
        BridgeStandardErrorCapture standardError)
    {
        _process = process;
        TemporaryRoot = temporaryRoot;
        _listening = listening;
        _standardError = standardError;
    }

    public string TemporaryRoot { get; }

    public int ProcessId => _process.Id;

    public string StandardError => _standardError.StandardError;

    public string LauncherDiagnostics => _standardError.LauncherDiagnostics;

    public static Task<BridgeProcessHarness> StartAsync(CancellationToken cancellationToken)
    {
        var temporaryRoot = Path.Combine(Path.GetTempPath(), $"birkin-live-bridge-{Guid.NewGuid():N}");
        var bridgeRoot = Path.Combine(temporaryRoot, "workspace");
        Directory.CreateDirectory(bridgeRoot);
        var listening = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        var standardError = new BridgeStandardErrorCapture();
        var start = new ProcessStartInfo
        {
            FileName = "uv",
            WorkingDirectory = FindRepositoryRoot(),
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };
        start.ArgumentList.Add("run");
        start.ArgumentList.Add("--frozen");
        start.ArgumentList.Add("birkin");
        start.ArgumentList.Add("native-bridge");
        start.ArgumentList.Add("serve");
        start.ArgumentList.Add("--transport");
        start.ArgumentList.Add("loopback");
        start.ArgumentList.Add("--root");
        start.ArgumentList.Add(bridgeRoot);

        var process = new Process { StartInfo = start, EnableRaisingEvents = true };
        process.OutputDataReceived += (_, eventArgs) =>
        {
            if (eventArgs.Data?.Contains("\"event\":\"listening\"", StringComparison.Ordinal) is true)
            {
                listening.TrySetResult(eventArgs.Data);
            }
        };
        process.ErrorDataReceived += (_, eventArgs) =>
        {
            if (eventArgs.Data is not null)
            {
                standardError.Append(eventArgs.Data);
            }
        };
        process.Exited += (_, _) => listening.TrySetException(
            new InvalidOperationException($"bridge exited before listening with code {process.ExitCode}"));

        try
        {
            if (!process.Start())
            {
                throw new InvalidOperationException("uv did not start");
            }
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            cancellationToken.Register(() => listening.TrySetCanceled(cancellationToken));
            return Task.FromResult(new BridgeProcessHarness(process, temporaryRoot, listening, standardError));
        }
        catch
        {
            process.Dispose();
            Directory.Delete(temporaryRoot, recursive: true);
            throw;
        }
    }

    public Task<string> WaitForListeningAsync(CancellationToken cancellationToken) =>
        _listening.Task.WaitAsync(cancellationToken);

    public async ValueTask DisposeAsync()
    {
        if (!_process.HasExited)
        {
            using var taskkill = Process.Start(new ProcessStartInfo
            {
                FileName = "taskkill.exe",
                UseShellExecute = false,
                CreateNoWindow = true,
                ArgumentList = { "/PID", _process.Id.ToString(System.Globalization.CultureInfo.InvariantCulture), "/T", "/F" },
            }) ?? throw new InvalidOperationException("taskkill did not start");
            await taskkill.WaitForExitAsync();
            if (taskkill.ExitCode != 0)
            {
                throw new InvalidOperationException($"taskkill failed with code {taskkill.ExitCode}");
            }
            await _process.WaitForExitAsync();
        }
        _process.Dispose();
        Directory.Delete(TemporaryRoot, recursive: true);
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "pyproject.toml")))
        {
            directory = directory.Parent;
        }
        return directory?.FullName ?? throw new InvalidOperationException("repository root was not found");
    }
}
