using System.Diagnostics;
using System.IO;
using Birkin.Native.Shell.Lifecycle;

namespace Birkin.Native.App.Startup;

internal sealed class OwnedBridgeProcess : IBridgeProcess, IBridgeAnnouncementSource
{
    private static readonly TimeSpan ExitTimeout = TimeSpan.FromSeconds(5);
    private readonly Process _process;
    private readonly EventHandler _processExited;
    private readonly TaskCompletionSource<string> _announcement =
        new(TaskCreationOptions.RunContinuationsAsynchronously);
    private int _stopped;
    private int _disposed;

    private OwnedBridgeProcess(Process process)
    {
        _process = process;
        _processExited = OnProcessExited;
        _process.Exited += _processExited;
        _process.EnableRaisingEvents = true;
        _ = ReadAnnouncementLineAsync();
    }

    public int ProcessId => _process.Id;

    public bool HasExited => _process.HasExited;

    public event Action<IBridgeProcess>? Exited;

    public static OwnedBridgeProcess Start(Action<IBridgeProcess> exited)
    {
        var executable = Environment.GetEnvironmentVariable("BIRKIN_EXECUTABLE") ?? "birkin";
        var executableArguments = Environment.GetEnvironmentVariable("BIRKIN_EXECUTABLE_ARGUMENTS");
        var startInfo = CreateStartInfo(executable, executableArguments);
        var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("The native bridge process could not be started.");
        var ownedProcess = new OwnedBridgeProcess(process);
        ownedProcess.Exited += exited;
        return ownedProcess;
    }

    internal static ProcessStartInfo CreateStartInfo(string executable, string? executableArguments)
    {
        const string bridgeArguments = "native-bridge serve --transport loopback";
        var arguments = string.IsNullOrWhiteSpace(executableArguments)
            ? bridgeArguments
            : $"{executableArguments} {bridgeArguments}";
        return new ProcessStartInfo(executable, arguments)
        {
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            UseShellExecute = false,
        };
    }

    public async ValueTask<string> ReadAnnouncementAsync(CancellationToken cancellationToken) =>
        await _announcement.Task.WaitAsync(cancellationToken).ConfigureAwait(false);

    public void Stop()
    {
        if (Interlocked.Exchange(ref _stopped, 1) != 0)
        {
            return;
        }

        if (_process.HasExited)
        {
            return;
        }

        _ = _process.CloseMainWindow();
        if (!_process.WaitForExit((int)ExitTimeout.TotalMilliseconds) && !_process.HasExited)
        {
            _process.Kill(entireProcessTree: false);
            _process.WaitForExit((int)ExitTimeout.TotalMilliseconds);
        }
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }

        _process.Exited -= _processExited;
        _process.Dispose();
    }

    private void OnProcessExited(object? sender, EventArgs eventArgs) => Exited?.Invoke(this);

    private async Task ReadAnnouncementLineAsync()
    {
        try
        {
            while (await _process.StandardOutput.ReadLineAsync().ConfigureAwait(false) is { } line)
            {
                if (!string.IsNullOrWhiteSpace(line))
                {
                    _announcement.TrySetResult(line);
                    return;
                }
            }

            _announcement.TrySetException(new InvalidDataException(
                "The owned bridge exited without announcing an endpoint."));
        }
        catch (Exception error)
        {
            _announcement.TrySetException(error);
        }
    }
}
