namespace Birkin.Native.Shell.Lifecycle;

public interface IBridgeProcess : IDisposable
{
    int ProcessId { get; }

    bool HasExited { get; }

    event Action<IBridgeProcess>? Exited;

    void Stop();
}

public interface IBridgeAnnouncementSource
{
    ValueTask<string> ReadAnnouncementAsync(CancellationToken cancellationToken);
}
