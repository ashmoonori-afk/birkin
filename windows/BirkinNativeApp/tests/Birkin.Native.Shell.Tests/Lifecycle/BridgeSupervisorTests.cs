using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Lifecycle;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Lifecycle;

[TestClass]
public sealed class BridgeSupervisorTests
{
    [TestMethod]
    public async Task ShutdownAsync_WhenAttachedExternally_LeavesMatchingAnnouncedProcessUntouched()
    {
        // Given
        var clock = new FakeMonotonicClock();
        var matchingExternalProcess = new FakeBridgeProcess(27192, []);
        var supervisor = new BridgeSupervisor(clock.Read, () => Return(matchingExternalProcess));
        supervisor.AttachExisting(Announcement(matchingExternalProcess.ProcessId));
        var shutdownCalls = new List<string>();

        // When
        await supervisor.ShutdownAsync(
            () => RecordAsync(shutdownCalls, "goodbye"),
            () => RecordAsync(shutdownCalls, "close"));

        // Then
        CollectionAssert.AreEqual(new[] { "goodbye", "close" }, shutdownCalls);
        Assert.AreEqual(0, matchingExternalProcess.StopCalls);
        Assert.AreEqual(0, matchingExternalProcess.DisposeCalls);
        Assert.AreEqual(0, matchingExternalProcess.SpawnReturns);
        Assert.AreEqual(BridgeSupervisorState.Stopped, supervisor.State);
        Assert.AreEqual(BridgeStopReason.AppShutdown, supervisor.StopReason);
    }

    [TestMethod]
    public async Task ShutdownAsync_WhenRunningOwned_StopsOnlyObjectReturnedBySpawnClosure()
    {
        // Given
        var clock = new FakeMonotonicClock();
        var shutdownCalls = new List<string>();
        var returnedProcess = new FakeBridgeProcess(27192, shutdownCalls);
        var samePidDecoy = new FakeBridgeProcess(returnedProcess.ProcessId, shutdownCalls);
        var supervisor = new BridgeSupervisor(clock.Read, () => Return(returnedProcess));
        Assert.IsTrue(supervisor.StartOwnedIfNeeded());

        // When
        await supervisor.ShutdownAsync(
            () => RecordAsync(shutdownCalls, "goodbye"),
            () => RecordAsync(shutdownCalls, "close"));

        // Then
        CollectionAssert.AreEqual(new[] { "goodbye", "close", "stop:27192" }, shutdownCalls);
        Assert.AreEqual(1, returnedProcess.StopCalls);
        Assert.AreEqual(0, samePidDecoy.StopCalls);
    }

    [TestMethod]
    public void ObserveExit_WhenFifthExitIsExactlySixtySecondsFromFirst_ClassifiesEdgeOutsideWindow()
    {
        // Given
        var clock = new FakeMonotonicClock();
        var spawned = new Queue<FakeBridgeProcess>(Enumerable.Range(1, 6).Select(index => new FakeBridgeProcess(index, [])));
        var supervisor = new BridgeSupervisor(clock.Read, () => Return(spawned.Dequeue()));
        Assert.IsTrue(supervisor.StartOwnedIfNeeded());
        foreach (var exitTime in new[] { TimeSpan.Zero, TimeSpan.FromSeconds(15), TimeSpan.FromSeconds(30), TimeSpan.FromSeconds(45) })
        {
            clock.Set(exitTime);
            Assert.IsNotNull(supervisor.OwnedProcess);
            supervisor.ObserveExit(supervisor.OwnedProcess);
        }

        // When
        clock.Set(TimeSpan.FromSeconds(60));
        Assert.IsNotNull(supervisor.OwnedProcess);
        supervisor.ObserveExit(supervisor.OwnedProcess);

        // Then
        Assert.AreEqual(BridgeSupervisorState.RunningOwned, supervisor.State);
        Assert.AreEqual(6, supervisor.OwnedProcessId);
        Assert.AreEqual(0, spawned.Count);
    }

    [TestMethod]
    public void ObserveExit_WhenFiveExitsFallInsideWindow_StopsUntilExplicitRetryStartsNewWindow()
    {
        // Given
        var clock = new FakeMonotonicClock();
        var spawned = new Queue<FakeBridgeProcess>(Enumerable.Range(1, 6).Select(index => new FakeBridgeProcess(index, [])));
        var supervisor = new BridgeSupervisor(clock.Read, () => Return(spawned.Dequeue()));
        var stoppedReasons = new List<BridgeStopReason>();
        supervisor.StoppedWithReason += stoppedReasons.Add;
        Assert.IsTrue(supervisor.StartOwnedIfNeeded());
        foreach (var exitTime in new[] { 0, 15, 30, 45 })
        {
            clock.Set(TimeSpan.FromSeconds(exitTime));
            Assert.IsNotNull(supervisor.OwnedProcess);
            supervisor.ObserveExit(supervisor.OwnedProcess);
        }

        // When
        clock.Set(TimeSpan.FromTicks(TimeSpan.FromSeconds(60).Ticks - 1));
        Assert.IsNotNull(supervisor.OwnedProcess);
        supervisor.ObserveExit(supervisor.OwnedProcess);

        // Then
        Assert.AreEqual(BridgeSupervisorState.Stopped, supervisor.State);
        Assert.AreEqual(BridgeStopReason.CrashLoop, supervisor.StopReason);
        Assert.IsNull(supervisor.OwnedProcessId);
        Assert.AreEqual(1, spawned.Count);
        CollectionAssert.AreEqual(
            new[] { BridgeStopReason.CrashLoop },
            stoppedReasons);
        Assert.IsTrue(supervisor.Retry());
        Assert.AreEqual(BridgeSupervisorState.RunningOwned, supervisor.State);
        Assert.AreEqual(6, supervisor.OwnedProcessId);
    }

    [TestMethod]
    public void StartOwnedIfNeeded_WhenProcessExitsDuringSpawn_LatchesExitAndRestartsExactlyOnce()
    {
        var first = new FakeBridgeProcess(1, []);
        var replacement = new FakeBridgeProcess(2, []);
        var spawnCalls = 0;
        BridgeSupervisor? supervisor = null;
        supervisor = new BridgeSupervisor(
            () => TimeSpan.Zero,
            () =>
            {
                spawnCalls++;
                if (spawnCalls == 1)
                {
                    supervisor!.ObserveExit(first);
                    return first;
                }

                return replacement;
            });

        Assert.IsTrue(supervisor.StartOwnedIfNeeded());

        Assert.AreEqual(2, spawnCalls);
        Assert.AreSame(replacement, supervisor.OwnedProcess);
        Assert.AreEqual(1, first.DisposeCalls);
        Assert.AreEqual(0, replacement.DisposeCalls);
    }

    [TestMethod]
    public void Retry_WhenLaunchFailed_StartsOwnedProcessAgain()
    {
        // Given
        var attempts = 0;
        var replacement = new FakeBridgeProcess(21, []);
        var supervisor = new BridgeSupervisor(
            () => TimeSpan.Zero,
            () =>
            {
                attempts++;
                return attempts == 1
                    ? throw new InvalidOperationException("missing executable")
                    : replacement;
            });
        Assert.IsFalse(supervisor.StartOwnedIfNeeded());

        // When
        var retried = supervisor.Retry();

        // Then
        Assert.IsTrue(retried);
        Assert.AreEqual(2, attempts);
        Assert.AreEqual(BridgeSupervisorState.RunningOwned, supervisor.State);
        Assert.AreSame(replacement, supervisor.OwnedProcess);
    }

    [TestMethod]
    public void StartOwnedIfNeeded_WhenProcessExitsAsHandlerIsRegistered_ObservesExitExactlyOnce()
    {
        var first = new FakeBridgeProcess(1, []) { ExitWhenObserved = true };
        var replacement = new FakeBridgeProcess(2, []);
        var spawned = new Queue<FakeBridgeProcess>([first, replacement]);
        var supervisor = new BridgeSupervisor(() => TimeSpan.Zero, () => Return(spawned.Dequeue()));

        Assert.IsTrue(supervisor.StartOwnedIfNeeded());

        Assert.AreSame(replacement, supervisor.OwnedProcess);
        Assert.AreEqual(1, first.DisposeCalls);
        Assert.AreEqual(0, spawned.Count);
    }

    [TestMethod]
    public async Task ShutdownAsync_WhenReplacementSpawnIsInFlight_DisposesItWithoutStartingAnother()
    {
        var first = new FakeBridgeProcess(1, []);
        var replacement = new FakeBridgeProcess(2, []);
        var replacementSpawnEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var allowReplacementReturn = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var spawnCalls = 0;
        var supervisor = new BridgeSupervisor(
            () => TimeSpan.Zero,
            () =>
            {
                spawnCalls++;
                if (spawnCalls == 1)
                {
                    return first;
                }

                replacementSpawnEntered.SetResult();
                allowReplacementReturn.Task.GetAwaiter().GetResult();
                return replacement;
            });
        Assert.IsTrue(supervisor.StartOwnedIfNeeded());

        var exit = Task.Run(first.Exit);
        await replacementSpawnEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        await supervisor.ShutdownAsync(
            () => ValueTask.CompletedTask,
            () => ValueTask.CompletedTask);
        allowReplacementReturn.SetResult();
        await exit.WaitAsync(TimeSpan.FromSeconds(5));

        Assert.AreEqual(2, spawnCalls);
        Assert.AreEqual(BridgeStopReason.AppShutdown, supervisor.StopReason);
        Assert.IsNull(supervisor.OwnedProcess);
        Assert.AreEqual(1, first.DisposeCalls);
        Assert.AreEqual(1, replacement.DisposeCalls);
        Assert.AreEqual(1, replacement.StopCalls);
    }

    [TestMethod]
    public void ObserveExit_WhenStaleProcessSignalsAfterReplacement_DoesNotAffectReplacement()
    {
        var first = new FakeBridgeProcess(1, []);
        var replacement = new FakeBridgeProcess(2, []);
        var spawned = new Queue<FakeBridgeProcess>([first, replacement]);
        var supervisor = new BridgeSupervisor(() => TimeSpan.Zero, () => Return(spawned.Dequeue()));
        Assert.IsTrue(supervisor.StartOwnedIfNeeded());
        first.Exit();
        Assert.AreSame(replacement, supervisor.OwnedProcess);

        supervisor.ObserveExit(first);

        Assert.AreSame(replacement, supervisor.OwnedProcess);
        Assert.AreEqual(1, first.DisposeCalls);
        Assert.AreEqual(0, replacement.DisposeCalls);
        Assert.AreEqual(0, spawned.Count);
    }

    [TestMethod]
    public async Task OwnedProcesses_AreDisposedExactlyOnceAcrossNaturalExitAndShutdown()
    {
        var first = new FakeBridgeProcess(1, []);
        var replacement = new FakeBridgeProcess(2, []);
        var spawned = new Queue<FakeBridgeProcess>([first, replacement]);
        var supervisor = new BridgeSupervisor(() => TimeSpan.Zero, () => Return(spawned.Dequeue()));
        Assert.IsTrue(supervisor.StartOwnedIfNeeded());

        first.Exit();
        await supervisor.ShutdownAsync(
            () => ValueTask.CompletedTask,
            () => ValueTask.CompletedTask);
        first.Exit();
        replacement.Exit();

        Assert.AreEqual(1, first.DisposeCalls);
        Assert.AreEqual(1, replacement.StopCalls);
        Assert.AreEqual(1, replacement.DisposeCalls);
    }

    [TestMethod]
    public async Task ShutdownAsync_WhenOwnedStopThrows_StillDisposesProcessExactlyOnce()
    {
        var process = new FakeBridgeProcess(1, []) { StopError = new InvalidOperationException("stop failed") };
        var supervisor = new BridgeSupervisor(() => TimeSpan.Zero, () => Return(process));
        Assert.IsTrue(supervisor.StartOwnedIfNeeded());

        var error = await Assert.ThrowsExceptionAsync<InvalidOperationException>(async () =>
            await supervisor.ShutdownAsync(
                () => ValueTask.CompletedTask,
                () => ValueTask.CompletedTask));

        Assert.AreEqual("stop failed", error.Message);
        Assert.AreEqual(1, process.StopCalls);
        Assert.AreEqual(1, process.DisposeCalls);
    }

    [TestMethod]
    public void ObserveExit_WhenDifferentObjectReusesOwnedPid_DoesNotRestartOrLoseOwnedProcess()
    {
        var owned = new FakeBridgeProcess(27192, []);
        var samePidExternal = new FakeBridgeProcess(27192, []);
        var spawnCalls = 0;
        var supervisor = new BridgeSupervisor(
            () => TimeSpan.Zero,
            () =>
            {
                spawnCalls++;
                return owned;
            });
        Assert.IsTrue(supervisor.StartOwnedIfNeeded());

        supervisor.ObserveExit(samePidExternal);

        Assert.AreSame(owned, supervisor.OwnedProcess);
        Assert.AreEqual(1, spawnCalls);
        Assert.AreEqual(BridgeSupervisorState.RunningOwned, supervisor.State);
    }

    private static BridgeAnnouncement Announcement(int processId) =>
        BridgeAnnouncement.Parse(TestBridgeAnnouncement.Json(processId));

    private static FakeBridgeProcess Return(FakeBridgeProcess process)
    {
        process.SpawnReturns++;
        return process;
    }

    private static ValueTask RecordAsync(List<string> calls, string call)
    {
        calls.Add(call);
        return ValueTask.CompletedTask;
    }

    private sealed class FakeMonotonicClock
    {
        private TimeSpan _now;

        public TimeSpan Read() => _now;

        public void Set(TimeSpan now) => _now = now;
    }

    private sealed class FakeBridgeProcess(int processId, List<string> calls) : IBridgeProcess
    {
        private bool _hasExited;

        public int ProcessId { get; } = processId;

        public bool HasExited
        {
            get
            {
                if (ExitWhenObserved)
                {
                    ExitWhenObserved = false;
                    Exit();
                }

                return _hasExited;
            }
        }

        public bool ExitWhenObserved { get; set; }

        public int SpawnReturns { get; set; }

        public int StopCalls { get; private set; }

        public int DisposeCalls { get; private set; }

        public Exception? StopError { get; set; }

        public event Action<IBridgeProcess>? Exited;

        public void Exit()
        {
            _hasExited = true;
            Exited?.Invoke(this);
        }

        public void Stop()
        {
            StopCalls++;
            calls.Add($"stop:{ProcessId}");
            if (StopError is not null)
            {
                throw StopError;
            }
        }

        public void Dispose() => DisposeCalls++;
    }
}
