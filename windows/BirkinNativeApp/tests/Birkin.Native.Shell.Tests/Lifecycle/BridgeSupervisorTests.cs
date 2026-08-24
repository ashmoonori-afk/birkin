using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Lifecycle;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Lifecycle;

[TestClass]
public sealed class BridgeSupervisorTests
{
    private const string InstanceId = "0123456789abcdef0123456789abcdef";

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
            Assert.IsNotNull(supervisor.OwnedProcessId);
            supervisor.ObserveExit(supervisor.OwnedProcessId.Value);
        }

        // When
        clock.Set(TimeSpan.FromSeconds(60));
        Assert.IsNotNull(supervisor.OwnedProcessId);
        supervisor.ObserveExit(supervisor.OwnedProcessId.Value);

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
        Assert.IsTrue(supervisor.StartOwnedIfNeeded());
        foreach (var exitTime in new[] { 0, 15, 30, 45 })
        {
            clock.Set(TimeSpan.FromSeconds(exitTime));
            Assert.IsNotNull(supervisor.OwnedProcessId);
            supervisor.ObserveExit(supervisor.OwnedProcessId.Value);
        }

        // When
        clock.Set(TimeSpan.FromTicks(TimeSpan.FromSeconds(60).Ticks - 1));
        Assert.IsNotNull(supervisor.OwnedProcessId);
        supervisor.ObserveExit(supervisor.OwnedProcessId.Value);

        // Then
        Assert.AreEqual(BridgeSupervisorState.Stopped, supervisor.State);
        Assert.AreEqual(BridgeStopReason.CrashLoop, supervisor.StopReason);
        Assert.IsNull(supervisor.OwnedProcessId);
        Assert.AreEqual(1, spawned.Count);
        Assert.IsTrue(supervisor.Retry());
        Assert.AreEqual(BridgeSupervisorState.RunningOwned, supervisor.State);
        Assert.AreEqual(6, supervisor.OwnedProcessId);
    }

    private static BridgeAnnouncement Announcement(int processId) => BridgeAnnouncement.Parse(
        $$"""{"event":"listening","transport":"loopback","pid":{{processId}},"root":"C:\\root","session_id":"session-1","instance_id":"{{InstanceId}}","server_version":"0.4.276","discovery_path":"C:\\root\\native\\endpoint.json"}""");

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
        public int ProcessId { get; } = processId;

        public int SpawnReturns { get; set; }

        public int StopCalls { get; private set; }

        public void Stop()
        {
            StopCalls++;
            calls.Add($"stop:{ProcessId}");
        }
    }
}
