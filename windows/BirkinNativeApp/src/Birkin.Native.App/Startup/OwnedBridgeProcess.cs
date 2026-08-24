using System.Diagnostics;
using System.IO;
using Birkin.Native.Shell.Lifecycle;

namespace Birkin.Native.App.Startup;

internal sealed class OwnedBridgeProcess : IBridgeProcess, IBridgeAnnouncementSource
{
    private static readonly TimeSpan ExitTimeout = TimeSpan.FromSeconds(5);
    private readonly Process _process;
    private readonly TaskCompletionSource<string> _announcement =
        new(TaskCreationOptions.RunContinuationsAsynchronously);
    private int _stopped;

    private OwnedBridgeProcess(Process process, Action<IBridgeProcess> exited)
    {
        _process = process;
        _process.EnableRaisingEvents = true;
        _process.Exited += (_, _) => exited(this);
        _ = ReadAnnouncementLineAsync();
    }

    public int ProcessId => _process.Id;

    public static OwnedBridgeProcess Start(Action<IBridgeProcess> exited)
    {
        var executable = Environment.GetEnvironmentVariable("BIRKIN_EXECUTABLE") ?? "birkin";
        var startInfo = new ProcessStartInfo(executable, "native-bridge serve --transport loopback")
        {
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            UseShellExecute = false,
        };
        var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("The native bridge process could not be started.");
        return new OwnedBridgeProcess(process, exited);
    }

    public async ValueTask<string> ReadAnnouncementAsync(CancellationToken cancellationToken) =>
        await _announcement.Task.WaitAsync(cancellationToken).ConfigureAwait(false);

    public void Stop()
    {
        if (Interlocked.Exchange(ref _stopped, 1) != 0)
        {
            return;
        }

        try
        {
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
        finally
        {
            _process.Dispose();
        }
    }

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
