using System.Diagnostics;
using System.IO;
using Birkin.Native.Shell.Lifecycle;

namespace Birkin.Native.App.Startup;

internal sealed class OwnedBridgeProcess : IBridgeProcess, IAsyncBridgeProcess, IBridgeAnnouncementSource
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
        var executable =
            Environment.GetEnvironmentVariable(
                ExecutablePathSettings.EnvironmentVariableName)
            ?? Environment.GetEnvironmentVariable(
                ExecutablePathSettings.EnvironmentVariableName,
                EnvironmentVariableTarget.User)
            ?? "birkin";
        return Start(exited, executable);
    }

    internal static OwnedBridgeProcess Start(
        Action<IBridgeProcess> exited,
        string executable)
    {
        var startInfo = new ProcessStartInfo(executable, "native-bridge serve --transport loopback")
        {
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            UseShellExecute = false,
        };
        var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("The native bridge process could not be started.");
        var ownedProcess = new OwnedBridgeProcess(process);
        ownedProcess.Exited += exited;
        return ownedProcess;
    }

    public async ValueTask<string> ReadAnnouncementAsync(CancellationToken cancellationToken) =>
        await _announcement.Task.WaitAsync(cancellationToken).ConfigureAwait(false);

    public void Stop()
    {
        if (Interlocked.Exchange(ref _stopped, 1) != 0 || _process.HasExited)
        {
            return;
        }

        _process.Kill(entireProcessTree: true);
    }

    public async ValueTask StopAsync(CancellationToken cancellationToken)
    {
        if (Interlocked.Exchange(ref _stopped, 1) != 0)
        {
            return;
        }

        await StopAsync(
            _process.CloseMainWindow,
            () => _process.HasExited,
            () => _process.Kill(entireProcessTree: true),
            token => _process.WaitForExitAsync(token),
            ExitTimeout,
            cancellationToken).ConfigureAwait(false);
    }

    internal static async ValueTask StopAsync(
        Func<bool> closeMainWindow,
        Func<bool> hasExited,
        Action killEntireProcessTree,
        Func<CancellationToken, Task> waitForExitAsync,
        TimeSpan exitTimeout,
        CancellationToken cancellationToken)
    {
        if (hasExited())
        {
            return;
        }

        if (!closeMainWindow())
        {
            killEntireProcessTree();
            await waitForExitAsync(cancellationToken)
                .WaitAsync(exitTimeout, cancellationToken)
                .ConfigureAwait(false);
            return;
        }

        try
        {
            await waitForExitAsync(cancellationToken)
                .WaitAsync(exitTimeout, cancellationToken)
                .ConfigureAwait(false);
        }
        catch (TimeoutException) when (!hasExited())
        {
            killEntireProcessTree();
            await waitForExitAsync(cancellationToken)
                .WaitAsync(exitTimeout, cancellationToken)
                .ConfigureAwait(false);
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
