namespace Birkin.Native.Shell.Lifecycle;

public interface IBridgeProcess
{
    int ProcessId { get; }

    void Stop();
}

public interface IBridgeAnnouncementSource
{
    ValueTask<string> ReadAnnouncementAsync(CancellationToken cancellationToken);
}
