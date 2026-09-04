using System.Diagnostics;
using System.IO;

namespace Birkin.Native.App.Tests.Support;

internal interface IOwnedBridgeProcess : IDisposable
{
    int Id { get; }

    bool HasExited { get; }

    void KillEntireProcessTree();

    Task WaitForExitAsync();
}

internal sealed class OwnedBridgeProcess : IOwnedBridgeProcess
{
    private readonly Process _process;

    public OwnedBridgeProcess(Process process) => _process = process;

    public int Id => _process.Id;

    public bool HasExited => _process.HasExited;

    public void KillEntireProcessTree() => _process.Kill(entireProcessTree: true);

    public Task WaitForExitAsync() => _process.WaitForExitAsync();

    public void Dispose() => _process.Dispose();
}

internal sealed class BridgeProcessHarness : IAsyncDisposable
{
    private readonly IOwnedBridgeProcess _process;
    private readonly TaskCompletionSource<string> _listening;
    private readonly BridgeStandardErrorCapture _standardError;

    internal BridgeProcessHarness(
        IOwnedBridgeProcess process,
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

    public bool OwnedProcessExited { get; private set; }

    public bool TemporaryRootDeleted { get; private set; }

    public static Task<BridgeProcessHarness> StartAsync(CancellationToken cancellationToken)
    {
        var temporaryRoot = Path.Combine(Path.GetTempPath(), $"birkin-live-bridge-{Guid.NewGuid():N}");
        var bridgeRoot = Path.Combine(temporaryRoot, "workspace");
        Directory.CreateDirectory(bridgeRoot);
        var listening = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        var standardError = new BridgeStandardErrorCapture();
        var start = CreateStartInfo(bridgeRoot);

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
            return Task.FromResult(new BridgeProcessHarness(
                new OwnedBridgeProcess(process),
                temporaryRoot,
                listening,
                standardError));
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
        await StopOwnedProcessAsync(_process);
        OwnedProcessExited = _process.HasExited;
        _process.Dispose();
        foreach (var file in Directory.EnumerateFiles(
            TemporaryRoot,
            "*",
            new EnumerationOptions
            {
                RecurseSubdirectories = true,
                AttributesToSkip = FileAttributes.ReparsePoint,
            }))
        {
            File.SetAttributes(file, File.GetAttributes(file) & ~FileAttributes.ReadOnly);
        }
        Directory.Delete(TemporaryRoot, recursive: true);
        TemporaryRootDeleted = !Directory.Exists(TemporaryRoot);
    }

    internal static async Task StopOwnedProcessAsync(IOwnedBridgeProcess process)
    {
        if (process.HasExited)
        {
            return;
        }

        try
        {
            process.KillEntireProcessTree();
        }
        catch (InvalidOperationException) when (process.HasExited)
        {
        }

        await process.WaitForExitAsync();
    }

    internal static ProcessStartInfo CreateStartInfo(string bridgeRoot)
    {
        Directory.CreateDirectory(Path.Combine(
            bridgeRoot,
            "workspace",
            "native-app",
            "receipts"));
        var repositoryRoot = FindRepositoryRoot();
        var python = Path.Combine(repositoryRoot, ".venv", "Scripts", "python.exe");
        var start = new ProcessStartInfo
        {
            FileName = File.Exists(python)
                ? python
                : throw new InvalidOperationException($"locked repository Python was not found: {python}"),
            WorkingDirectory = repositoryRoot,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };
        start.Environment["BIRKIN_HOME"] = Path.Combine(
            Path.GetDirectoryName(bridgeRoot)
            ?? throw new InvalidOperationException("bridge root has no parent directory"),
            "home");
        start.ArgumentList.Add("-m");
        start.ArgumentList.Add("birkin.native.serve");
        start.ArgumentList.Add("--transport");
        start.ArgumentList.Add("loopback");
        start.ArgumentList.Add("--root");
        start.ArgumentList.Add(bridgeRoot);
        return start;
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
