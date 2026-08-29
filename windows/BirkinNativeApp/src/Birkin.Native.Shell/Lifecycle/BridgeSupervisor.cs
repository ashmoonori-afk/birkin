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
    StartupFailed,
    StartupTimeout,
}

public sealed class BridgeSupervisor
{
    private static readonly TimeSpan CrashWindow = TimeSpan.FromSeconds(60);
    private const int CrashLimit = 5;

    private readonly object _gate = new();
    private readonly Func<TimeSpan> _clock;
    private readonly Func<IBridgeProcess> _spawn;
    private readonly List<TimeSpan> _exitTimes = [];
    private readonly HashSet<IBridgeProcess> _exitsDuringStart =
        new(ReferenceEqualityComparer.Instance);
    private SupervisorLifecycle _lifecycle;
    private long _generation;
    private IBridgeProcess? _ownedProcess;
    private BridgeSupervisorState _state;
    private BridgeStopReason? _stopReason;
    private BridgeAttachment? _attachment;

    public BridgeSupervisor(Func<TimeSpan> clock, Func<IBridgeProcess> spawn)
    {
        _clock = clock;
        _spawn = spawn;
    }

    public BridgeSupervisorState State
    {
        get
        {
            lock (_gate)
            {
                return _state;
            }
        }
    }

    public BridgeStopReason? StopReason
    {
        get
        {
            lock (_gate)
            {
                return _stopReason;
            }
        }
    }

    public BridgeAttachment? Attachment
    {
        get
        {
            lock (_gate)
            {
                return _attachment;
            }
        }
    }

    public IBridgeProcess? OwnedProcess
    {
        get
        {
            lock (_gate)
            {
                return _ownedProcess;
            }
        }
    }

    public int? OwnedProcessId
    {
        get
        {
            lock (_gate)
            {
                return _ownedProcess?.ProcessId;
            }
        }
    }

    public event Action<IBridgeProcess>? OwnedProcessStarted;

    public event Action<BridgeStopReason>? StoppedWithReason;

    public void AttachExisting(BridgeAnnouncement announcement)
    {
        lock (_gate)
        {
            if (_lifecycle != SupervisorLifecycle.Idle)
            {
                return;
            }

            _attachment = new BridgeAttachment.AttachedExternal(announcement);
            _state = BridgeSupervisorState.AttachedExternal;
            _lifecycle = SupervisorLifecycle.AttachedExternal;
        }
    }

    public bool StartOwnedIfNeeded()
    {
        long generation;
        lock (_gate)
        {
            if (_lifecycle != SupervisorLifecycle.Idle)
            {
                return false;
            }

            generation = BeginLaunchLocked();
        }

        return CompleteLaunch(generation);
    }

    public void ObserveExit(IBridgeProcess process)
    {
        IBridgeProcess? exitedProcess = null;
        long? replacementGeneration = null;
        BridgeStopReason? stoppedReason = null;

        lock (_gate)
        {
            if (_lifecycle == SupervisorLifecycle.Starting)
            {
                _ = _exitsDuringStart.Add(process);
                return;
            }

            if (_lifecycle != SupervisorLifecycle.Running
                || !ReferenceEquals(_ownedProcess, process))
            {
                return;
            }

            process.Exited -= ObserveExit;
            exitedProcess = process;
            _ownedProcess = null;
            _attachment = null;

            var now = _clock();
            _exitTimes.RemoveAll(exitTime => now - exitTime >= CrashWindow);
            _exitTimes.Add(now);
            if (_exitTimes.Count >= CrashLimit)
            {
                _lifecycle = SupervisorLifecycle.Stopped;
                _state = BridgeSupervisorState.Stopped;
                _stopReason = BridgeStopReason.CrashLoop;
                stoppedReason = BridgeStopReason.CrashLoop;
            }
            else
            {
                replacementGeneration = BeginLaunchLocked();
            }
        }

        exitedProcess.Dispose();
        if (stoppedReason is { } reason)
        {
            StoppedWithReason?.Invoke(reason);
        }
        if (replacementGeneration is { } generation)
        {
            _ = CompleteLaunch(generation);
        }
    }

    public bool Retry()
    {
        long generation;
        lock (_gate)
        {
            if (_lifecycle != SupervisorLifecycle.Stopped
                || _stopReason is not (
                    BridgeStopReason.CrashLoop
                    or BridgeStopReason.LaunchFailed
                    or BridgeStopReason.StartupFailed
                    or BridgeStopReason.StartupTimeout))
            {
                return false;
            }

            _exitTimes.Clear();
            _state = BridgeSupervisorState.Idle;
            _stopReason = null;
            _lifecycle = SupervisorLifecycle.Idle;
            generation = BeginLaunchLocked();
        }

        return CompleteLaunch(generation);
    }

    internal async ValueTask StopOwnedAsync(BridgeStopReason reason)
    {
        _ = await StopOwnedAsyncCore(
            expectedProcess: null,
            reason).ConfigureAwait(false);
    }

    internal ValueTask<bool> StopOwnedAsync(
        IBridgeProcess expectedProcess,
        BridgeStopReason reason) =>
        StopOwnedAsyncCore(expectedProcess, reason);

    private async ValueTask<bool> StopOwnedAsyncCore(
        IBridgeProcess? expectedProcess,
        BridgeStopReason reason)
    {
        IBridgeProcess? ownedProcess;
        lock (_gate)
        {
            if (_lifecycle != SupervisorLifecycle.Running
                || _ownedProcess is null
                || (
                    expectedProcess is not null
                    && !ReferenceEquals(_ownedProcess, expectedProcess)
                ))
            {
                return false;
            }

            _generation++;
            ownedProcess = _ownedProcess;
            ownedProcess.Exited -= ObserveExit;
            _ownedProcess = null;
            _attachment = null;
            _exitTimes.Clear();
            _state = BridgeSupervisorState.Stopped;
            _stopReason = reason;
            _lifecycle = SupervisorLifecycle.Stopped;
        }

        await StopAndDisposeAsync(ownedProcess).ConfigureAwait(false);
        StoppedWithReason?.Invoke(reason);
        return true;
    }

    public async ValueTask ShutdownAsync(
        Func<ValueTask> sendGoodbye,
        Func<ValueTask> closeConnection)
    {
        IBridgeProcess? ownedProcess;
        lock (_gate)
        {
            if (_lifecycle == SupervisorLifecycle.Disposed)
            {
                return;
            }

            _lifecycle = SupervisorLifecycle.Disposed;
            _generation++;
            _exitsDuringStart.Clear();
            ownedProcess = _ownedProcess;
            if (ownedProcess is not null)
            {
                ownedProcess.Exited -= ObserveExit;
            }

            _ownedProcess = null;
            _attachment = null;
            _state = BridgeSupervisorState.Stopped;
            _stopReason = BridgeStopReason.AppShutdown;
        }

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
                if (ownedProcess is not null)
                {
                    await StopAndDisposeAsync(ownedProcess).ConfigureAwait(false);
                }
            }
        }
    }

    private long BeginLaunchLocked()
    {
        _lifecycle = SupervisorLifecycle.Starting;
        _exitsDuringStart.Clear();
        return ++_generation;
    }

    private bool CompleteLaunch(long generation)
    {
        IBridgeProcess process;
        try
        {
            process = _spawn();
        }
        catch (Exception)
        {
            var stopped = false;
            lock (_gate)
            {
                if (_lifecycle == SupervisorLifecycle.Starting
                    && _generation == generation)
                {
                    _exitsDuringStart.Clear();
                    _lifecycle = SupervisorLifecycle.Stopped;
                    _state = BridgeSupervisorState.Stopped;
                    _stopReason = BridgeStopReason.LaunchFailed;
                    stopped = true;
                }
            }

            if (stopped)
            {
                StoppedWithReason?.Invoke(BridgeStopReason.LaunchFailed);
            }
            return false;
        }

        bool exitedDuringStart;
        bool rejected;
        lock (_gate)
        {
            rejected = _lifecycle != SupervisorLifecycle.Starting
                || _generation != generation;
            if (!rejected)
            {
                _ownedProcess = process;
                process.Exited += ObserveExit;
                exitedDuringStart = _exitsDuringStart.Remove(process);
                _exitsDuringStart.Clear();
                _attachment = new BridgeAttachment.RunningOwned(process.ProcessId);
                _state = BridgeSupervisorState.RunningOwned;
                _stopReason = null;
                _lifecycle = SupervisorLifecycle.Running;
            }
            else
            {
                exitedDuringStart = false;
            }
        }

        if (rejected)
        {
            StopAndDispose(process);
            return false;
        }

        bool hasExited;
        try
        {
            hasExited = process.HasExited;
        }
        catch (InvalidOperationException) when (!OwnsProcess(process, generation))
        {
            hasExited = true;
        }

        if (exitedDuringStart || hasExited)
        {
            ObserveExit(process);
        }

        Action<IBridgeProcess>? started;
        lock (_gate)
        {
            if (_lifecycle != SupervisorLifecycle.Running
                || _generation != generation
                || !ReferenceEquals(_ownedProcess, process))
            {
                return _state == BridgeSupervisorState.RunningOwned;
            }

            started = OwnedProcessStarted;
        }

        started?.Invoke(process);
        return true;
    }

    private bool OwnsProcess(IBridgeProcess process, long generation)
    {
        lock (_gate)
        {
            return _lifecycle == SupervisorLifecycle.Running
                && _generation == generation
                && ReferenceEquals(_ownedProcess, process);
        }
    }

    internal bool OwnsProcess(IBridgeProcess process)
    {
        lock (_gate)
        {
            return _lifecycle == SupervisorLifecycle.Running
                && ReferenceEquals(_ownedProcess, process);
        }
    }

    private static async ValueTask StopAndDisposeAsync(IBridgeProcess process)
    {
        try
        {
            if (process is IAsyncBridgeProcess asyncProcess)
            {
                await asyncProcess.StopAsync(CancellationToken.None).ConfigureAwait(false);
            }
            else
            {
                process.Stop();
            }
        }
        finally
        {
            process.Dispose();
        }
    }

    private static void StopAndDispose(IBridgeProcess process)
    {
        try
        {
            process.Stop();
        }
        finally
        {
            process.Dispose();
        }
    }

    private enum SupervisorLifecycle
    {
        Idle,
        Starting,
        Running,
        AttachedExternal,
        Stopped,
        Disposed,
    }
}
