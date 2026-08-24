using Birkin.Native.Protocol.Transport;

namespace Birkin.Native.Shell.Lifecycle;

public enum BridgeSupervisorState
{
    Idle,
    AttachedExternal,
    RunningOwned,
    Stopped,
}

public enum BridgeStopReason
{
    AppShutdown,
    CrashLoop,
    LaunchFailed,
}

public sealed class BridgeSupervisor
{
    private static readonly TimeSpan CrashWindow = TimeSpan.FromSeconds(60);
    private const int CrashLimit = 5;

    private readonly Func<TimeSpan> _clock;
    private readonly Func<IBridgeProcess> _spawn;
    private readonly List<TimeSpan> _exitTimes = [];
    private IBridgeProcess? _ownedProcess;

    public BridgeSupervisor(Func<TimeSpan> clock, Func<IBridgeProcess> spawn)
    {
        _clock = clock;
        _spawn = spawn;
    }

    public BridgeSupervisorState State { get; private set; }

    public BridgeStopReason? StopReason { get; private set; }

    public BridgeAttachment? Attachment { get; private set; }

    public int? OwnedProcessId => _ownedProcess?.ProcessId;

    public void AttachExisting(BridgeAnnouncement announcement)
    {
        if (State != BridgeSupervisorState.Idle)
        {
            return;
        }

        Attachment = new BridgeAttachment.AttachedExternal(announcement);
        State = BridgeSupervisorState.AttachedExternal;
    }

    public bool StartOwnedIfNeeded() => State == BridgeSupervisorState.Idle && LaunchOwned();

    public void ObserveExit(int processId)
    {
        if (_ownedProcess is null || _ownedProcess.ProcessId != processId)
        {
            return;
        }

        _ownedProcess = null;
        Attachment = null;
        var now = _clock();
        _exitTimes.RemoveAll(exitTime => now - exitTime >= CrashWindow);
        _exitTimes.Add(now);
        if (_exitTimes.Count >= CrashLimit)
        {
            State = BridgeSupervisorState.Stopped;
            StopReason = BridgeStopReason.CrashLoop;
            return;
        }

        _ = LaunchOwned();
    }

    public bool Retry()
    {
        if (State != BridgeSupervisorState.Stopped || StopReason != BridgeStopReason.CrashLoop)
        {
            return false;
        }

        _exitTimes.Clear();
        State = BridgeSupervisorState.Idle;
        StopReason = null;
        return LaunchOwned();
    }

    public async ValueTask ShutdownAsync(
        Func<ValueTask> sendGoodbye,
        Func<ValueTask> closeConnection)
    {
        try
        {
            await sendGoodbye().ConfigureAwait(false);
        }
        finally
        {
            try
            {
                await closeConnection().ConfigureAwait(false);
            }
            finally
            {
                var ownedProcess = _ownedProcess;
                _ownedProcess = null;
                Attachment = null;
                State = BridgeSupervisorState.Stopped;
                StopReason = BridgeStopReason.AppShutdown;
                ownedProcess?.Stop();
            }
        }
    }

    private bool LaunchOwned()
    {
        try
        {
            var process = _spawn();
            _ownedProcess = process;
            Attachment = new BridgeAttachment.RunningOwned(process.ProcessId);
            State = BridgeSupervisorState.RunningOwned;
            StopReason = null;
            return true;
        }
        catch (Exception)
        {
            _ownedProcess = null;
            Attachment = null;
            State = BridgeSupervisorState.Stopped;
            StopReason = BridgeStopReason.LaunchFailed;
            return false;
        }
    }
}
