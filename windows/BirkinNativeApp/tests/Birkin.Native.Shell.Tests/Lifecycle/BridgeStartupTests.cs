using System.ComponentModel;
using System.IO;
using Birkin.Native.Shell.Lifecycle;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Lifecycle;

[TestClass]
public sealed class BridgeStartupTests
{
    [TestMethod]
    public async Task StartOwnedAsync_WhenCliCannotLaunch_ReturnsUnavailableFailure()
    {
        // Given
        var supervisor = new BridgeSupervisor(
            () => TimeSpan.Zero,
            () => throw new InvalidOperationException("missing executable"));

        // When
        var result = await BridgeStartup.StartOwnedAsync(
            supervisor,
            CancellationToken.None);

        // Then
        var failure = result as BridgeStartupResult.Failed;
        Assert.IsNotNull(failure);
        Assert.AreEqual(
            BridgeStartupFailureReason.CliUnavailable,
            failure.Reason);
        Assert.AreEqual(BridgeStopReason.LaunchFailed, supervisor.StopReason);
    }

    [TestMethod]
    public async Task StartOwnedAsync_WhenWindowsCannotFindExecutable_ReturnsUnavailableFailure()
    {
        // Given
        var supervisor = new BridgeSupervisor(
            () => TimeSpan.Zero,
            () => throw new Win32Exception(2, "file not found"));

        // When
        var result = await BridgeStartup.StartOwnedAsync(
            supervisor,
            CancellationToken.None);

        // Then
        var failure = result as BridgeStartupResult.Failed;
        Assert.IsNotNull(failure);
        Assert.AreEqual(
            BridgeStartupFailureReason.CliUnavailable,
            failure.Reason);
        Assert.AreEqual(BridgeSupervisorState.Stopped, supervisor.State);
        Assert.AreEqual(BridgeStopReason.LaunchFailed, supervisor.StopReason);
    }

    [TestMethod]
    public async Task StartOwnedAsync_WhenCliExitsBeforeAnnouncement_ReturnsStartupFailure()
    {
        // Given
        var process = new FailingAnnouncementProcess(
            new InvalidDataException("bridge exited before announcement"));
        var supervisor = new BridgeSupervisor(
            () => TimeSpan.Zero,
            () => process);

        // When
        var result = await BridgeStartup.StartOwnedAsync(
            supervisor,
            CancellationToken.None);

        // Then
        var failure = result as BridgeStartupResult.Failed;
        Assert.IsNotNull(failure);
        Assert.AreEqual(
            BridgeStartupFailureReason.CliFailed,
            failure.Reason);
    }

    [TestMethod]
    public async Task StartOwnedAsync_WhenAnnouncementReaderFails_ReturnsStartupFailure()
    {
        // Given
        var process = new FailingAnnouncementProcess(
            new ObjectDisposedException("stdout"));
        var supervisor = new BridgeSupervisor(
            () => TimeSpan.Zero,
            () => process);

        // When
        var result = await BridgeStartup.StartOwnedAsync(
            supervisor,
            CancellationToken.None);

        // Then
        var failure = result as BridgeStartupResult.Failed;
        Assert.IsNotNull(failure);
        Assert.AreEqual(
            BridgeStartupFailureReason.CliFailed,
            failure.Reason);
    }

    [TestMethod]
    public async Task StartOwnedAsync_WhenAnnouncementIsReady_ReturnsOwnedReady()
    {
        // Given
        var process = new ReadyAnnouncementProcess("owned-ready");
        var supervisor = new BridgeSupervisor(
            () => TimeSpan.Zero,
            () => process);

        // When
        var result = await BridgeStartup.StartOwnedAsync(
            supervisor,
            CancellationToken.None);

        // Then
        var ready = result as BridgeStartupResult.OwnedReady;
        Assert.IsNotNull(ready);
        Assert.AreEqual("owned-ready", ready.AnnouncementJson);
    }

    [TestMethod]
    public async Task StartOwnedAsync_WhenAnnouncementTimesOut_StopsOwnedProcess()
    {
        // Given
        var process = new NeverAnnouncingProcess();
        var supervisor = new BridgeSupervisor(
            () => TimeSpan.Zero,
            () => process);

        // When
        var result = await BridgeStartup.StartOwnedAsync(
            supervisor,
            TimeSpan.Zero,
            CancellationToken.None);

        // Then
        var failure = result as BridgeStartupResult.Failed;
        Assert.IsNotNull(failure);
        Assert.AreEqual(
            BridgeStartupFailureReason.CliTimedOut,
            failure.Reason);
        Assert.AreEqual(
            BridgeStopReason.StartupTimeout,
            supervisor.StopReason);
        Assert.AreEqual(1, process.StopCalls);
        Assert.AreEqual(1, process.DisposeCalls);
    }

    [TestMethod]
    public async Task WaitForOwnedAsync_WhenReplacementNeverAnnounces_StopsOwnedProcess()
    {
        // Given
        var process = new NeverAnnouncingProcess();
        var supervisor = new BridgeSupervisor(
            () => TimeSpan.Zero,
            () => process);
        Assert.IsTrue(supervisor.StartOwnedIfNeeded());

        // When
        var result = await BridgeStartup.WaitForOwnedAsync(
            supervisor,
            process,
            TimeSpan.Zero,
            CancellationToken.None);

        // Then
        var failure = result as BridgeStartupResult.Failed;
        Assert.IsNotNull(failure);
        Assert.AreEqual(
            BridgeStartupFailureReason.CliTimedOut,
            failure.Reason);
        Assert.AreEqual(
            BridgeStopReason.StartupTimeout,
            supervisor.StopReason);
        Assert.AreEqual(1, process.StopCalls);
        Assert.AreEqual(1, process.DisposeCalls);
    }

    [TestMethod]
    public async Task StartOwnedAsync_WhenProcessImmediatelyCrashLoops_ReturnsCrashLoopFailure()
    {
        // Given
        var supervisor = new BridgeSupervisor(
            () => TimeSpan.Zero,
            () => new ImmediatelyExitedProcess());

        // When
        var result = await BridgeStartup.StartOwnedAsync(
            supervisor,
            CancellationToken.None);

        // Then
        var failure = result as BridgeStartupResult.Failed;
        Assert.IsNotNull(failure);
        Assert.AreEqual(
            BridgeStartupFailureReason.CliCrashLoop,
            failure.Reason);
        Assert.AreEqual(
            BridgeStopReason.CrashLoop,
            supervisor.StopReason);
    }

    [TestMethod]
    public async Task WaitForOwnedAsync_WhenObservedProcessIsReplaced_DoesNotStopReplacement()
    {
        // Given
        var first = new ControllableAnnouncementProcess();
        var replacement = new ReadyAnnouncementProcess(
            "replacement-ready");
        var attempts = 0;
        var supervisor = new BridgeSupervisor(
            () => TimeSpan.Zero,
            () => ++attempts == 1 ? first : replacement);
        Assert.IsTrue(supervisor.StartOwnedIfNeeded());
        var waiting = BridgeStartup.WaitForOwnedAsync(
            supervisor,
            first,
            TimeSpan.FromSeconds(5),
            CancellationToken.None);

        // When
        first.Exit();
        first.FailAnnouncement(
            new InvalidDataException("stale process failed"));
        _ = await waiting;

        // Then
        Assert.AreSame(replacement, supervisor.OwnedProcess);
        Assert.AreEqual(BridgeSupervisorState.RunningOwned, supervisor.State);
        Assert.AreEqual(0, replacement.StopCalls);
        Assert.AreEqual(0, replacement.DisposeCalls);
    }

    [TestMethod]
    public async Task StartOwnedAsync_WhenProcessIsReplacedDuringAnnouncement_FollowsReplacement()
    {
        // Given
        var first = new ControllableAnnouncementProcess();
        var replacement = new ReadyAnnouncementProcess(
            "replacement-ready");
        var attempts = 0;
        var supervisor = new BridgeSupervisor(
            () => TimeSpan.Zero,
            () => ++attempts == 1 ? first : replacement);
        var starting = BridgeStartup.StartOwnedAsync(
            supervisor,
            TimeSpan.FromSeconds(5),
            CancellationToken.None);

        // When
        first.Exit();
        first.FailAnnouncement(
            new InvalidDataException("stale process failed"));
        var result = await starting;

        // Then
        var ready = result as BridgeStartupResult.OwnedReady;
        Assert.IsNotNull(ready);
        Assert.AreEqual(
            "replacement-ready",
            ready.AnnouncementJson);
        Assert.AreSame(replacement, supervisor.OwnedProcess);
    }

    [TestMethod]
    public async Task StartOwnedAsync_WhenReplacementSeriesCrashLoops_ReturnsCurrentCrashLoop()
    {
        // Given
        var first = new ControllableAnnouncementProcess();
        var attempts = 0;
        var supervisor = new BridgeSupervisor(
            () => TimeSpan.Zero,
            () => ++attempts == 1
                ? first
                : new ImmediatelyExitedProcess());
        var starting = BridgeStartup.StartOwnedAsync(
            supervisor,
            TimeSpan.FromSeconds(5),
            CancellationToken.None);

        // When
        first.Exit();
        first.FailAnnouncement(
            new InvalidDataException("stale process failed"));
        var result = await starting;

        // Then
        var failure = result as BridgeStartupResult.Failed;
        Assert.IsNotNull(failure);
        Assert.AreEqual(
            BridgeStartupFailureReason.CliCrashLoop,
            failure.Reason);
        Assert.AreEqual(
            BridgeStopReason.CrashLoop,
            supervisor.StopReason);
    }

    [TestMethod]
    public async Task StartOwnedAsync_AfterRetry_UsesAlreadyStartedProcess()
    {
        // Given
        var attempts = 0;
        var replacement = new ReadyAnnouncementProcess("retry-ready");
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
        Assert.IsTrue(supervisor.Retry());

        // When
        var result = await BridgeStartup.StartOwnedAsync(
            supervisor,
            CancellationToken.None);

        // Then
        var ready = result as BridgeStartupResult.OwnedReady;
        Assert.IsNotNull(ready);
        Assert.AreEqual("retry-ready", ready.AnnouncementJson);
        Assert.AreEqual(2, attempts);
    }

    [TestMethod]
    public void ParseAttached_WhenAnnouncementIsMalformed_ReturnsStartupFailure()
    {
        // Given
        const string malformedAnnouncement = "{\"transport\":\"loopback\"";

        // When
        var result = BridgeStartup.ParseAttached(malformedAnnouncement);

        // Then
        var failure = result as BridgeStartupResult.Failed;
        Assert.IsNotNull(failure);
        Assert.AreEqual(
            BridgeStartupFailureReason.CliFailed,
            failure.Reason);
    }

    [TestMethod]
    public void ParseAttached_WhenAnnouncementIsValid_ReturnsAttachedReady()
    {
        // Given
        var announcementJson = TestBridgeAnnouncement.Json();

        // When
        var result = BridgeStartup.ParseAttached(announcementJson);

        // Then
        var ready = result as BridgeStartupResult.AttachedReady;
        Assert.IsNotNull(ready);
        Assert.AreEqual(announcementJson, ready.AnnouncementJson);
        Assert.AreEqual("session-1", ready.Announcement.SessionId);
    }

    private sealed class FailingAnnouncementProcess :
        IBridgeProcess,
        IBridgeAnnouncementSource
    {
        private readonly Exception _error;

        public FailingAnnouncementProcess(Exception error) => _error = error;

        public int ProcessId => 7;

        public bool HasExited => false;

        public event Action<IBridgeProcess>? Exited
        {
            add { }
            remove { }
        }

        public ValueTask<string> ReadAnnouncementAsync(
            CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            return ValueTask.FromException<string>(
                _error);
        }

        public void Stop()
        {
        }

        public void Dispose()
        {
        }
    }

    private sealed class ReadyAnnouncementProcess :
        IBridgeProcess,
        IBridgeAnnouncementSource
    {
        private readonly string _announcementJson;

        public ReadyAnnouncementProcess(string announcementJson) =>
            _announcementJson = announcementJson;

        public int ProcessId => 8;

        public bool HasExited => false;

        public int StopCalls { get; private set; }

        public int DisposeCalls { get; private set; }

        public event Action<IBridgeProcess>? Exited
        {
            add { }
            remove { }
        }

        public ValueTask<string> ReadAnnouncementAsync(
            CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            return ValueTask.FromResult(_announcementJson);
        }

        public void Stop() => StopCalls++;

        public void Dispose() => DisposeCalls++;
    }

    private sealed class NeverAnnouncingProcess :
        IBridgeProcess,
        IBridgeAnnouncementSource
    {
        private readonly TaskCompletionSource<string> _announcement =
            new(TaskCreationOptions.RunContinuationsAsynchronously);

        public int ProcessId => 9;

        public bool HasExited => false;

        public int StopCalls { get; private set; }

        public int DisposeCalls { get; private set; }

        public event Action<IBridgeProcess>? Exited
        {
            add { }
            remove { }
        }

        public ValueTask<string> ReadAnnouncementAsync(
            CancellationToken cancellationToken) =>
            new(_announcement.Task.WaitAsync(cancellationToken));

        public void Stop() => StopCalls++;

        public void Dispose() => DisposeCalls++;
    }

    private sealed class ImmediatelyExitedProcess : IBridgeProcess
    {
        public int ProcessId => 10;

        public bool HasExited => true;

        public event Action<IBridgeProcess>? Exited
        {
            add { }
            remove { }
        }

        public void Stop()
        {
        }

        public void Dispose()
        {
        }
    }

    private sealed class ControllableAnnouncementProcess :
        IBridgeProcess,
        IBridgeAnnouncementSource
    {
        private readonly TaskCompletionSource<string> _announcement =
            new(TaskCreationOptions.RunContinuationsAsynchronously);
        private Action<IBridgeProcess>? _exited;

        public int ProcessId => 11;

        public bool HasExited { get; private set; }

        public event Action<IBridgeProcess>? Exited
        {
            add => _exited += value;
            remove => _exited -= value;
        }

        public ValueTask<string> ReadAnnouncementAsync(
            CancellationToken cancellationToken) =>
            new(_announcement.Task.WaitAsync(cancellationToken));

        public void Exit()
        {
            HasExited = true;
            _exited?.Invoke(this);
        }

        public void FailAnnouncement(Exception error) =>
            _announcement.TrySetException(error);

        public void Stop()
        {
        }

        public void Dispose()
        {
        }
    }
}
