namespace Birkin.Native.Shell.Lifecycle;

public interface IBridgeProcess
{
    int ProcessId { get; }

    void Stop();
}
