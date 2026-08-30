using System.ComponentModel;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Lifecycle;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Presentation;

[TestClass]
public sealed class ShellPresentationModelTests
{
    [TestMethod]
    public void PresentConnection_WhenCalledOffContext_MarshalsNotificationThroughInjectedContext()
    {
        // Given
        var context = new DeterministicSynchronizationContext();
        var model = new ShellPresentationModel(context);
        var notifications = new List<string?>();
        model.PropertyChanged += (_, change) => notifications.Add(change.PropertyName);

        // When
        model.PresentConnection(ConnectionPresentation.Create(ConnectionState.Connecting));

        // Then
        Assert.AreEqual(ConnectionState.Disconnected, model.Connection.State);
        Assert.AreEqual(0, notifications.Count);
        context.RunAll();
        Assert.AreEqual(ConnectionState.Connecting, model.Connection.State);
        CollectionAssert.AreEqual(new[] { nameof(ShellPresentationModel.Connection) }, notifications);
    }

    [TestMethod]
    public void PresentSnapshot_WhenPublished_ChangesImmutableWorkspaceBeforeCallback()
    {
        // Given
        var context = new DeterministicSynchronizationContext();
        var model = new ShellPresentationModel(context);
        var snapshot = new WorkspaceSnapshotPresentation(
            ProtocolVersion: 1,
            SessionId: "session-1",
            Cursor: 42,
            InstanceId: "0123456789abcdef0123456789abcdef",
            ResetReason: "initial",
            Transport: "loopback",
            PanelCount: 3);
        WorkspaceSnapshotPresentation? observed = null;

        // When
        model.PresentSnapshot(snapshot, () => observed = model.Workspace);
        context.RunAll();

        // Then
        Assert.AreSame(snapshot, model.Workspace);
        Assert.AreSame(snapshot, observed);
    }

    [TestMethod]
    public void PresentReadySnapshot_WhenPublished_CommitsReadyConnectionAndWorkspaceAtomically()
    {
        // Given
        var context = new DeterministicSynchronizationContext();
        var model = new ShellPresentationModel(context);
        var snapshot = new WorkspaceSnapshotPresentation(
            ProtocolVersion: 1,
            SessionId: "session-1",
            Cursor: 42,
            InstanceId: "0123456789abcdef0123456789abcdef",
            ResetReason: "initial",
            Transport: "loopback",
            PanelCount: 3);
        (ConnectionState State, WorkspaceSnapshotPresentation? Workspace)? observed = null;

        // When
        model.PresentReadySnapshot(snapshot, () => observed = (model.Connection.State, model.Workspace));
        context.RunAll();

        // Then
        Assert.AreEqual(ConnectionState.Ready, observed?.State);
        Assert.AreSame(snapshot, observed?.Workspace);
    }

    [TestMethod]
    public void PresentStartupFailure_WhenCliIsUnavailable_ExposesPersistentExplanation()
    {
        // Given
        var context = new DeterministicSynchronizationContext();
        var model = new ShellPresentationModel(context);
        var failure = StartupFailurePresentation.Create(
            BridgeStartupFailureReason.CliUnavailable);

        // When
        model.PresentStartupFailure(failure);
        context.RunAll();

        // Then
        Assert.AreSame(failure, model.StartupFailure);
        Assert.IsTrue(model.HasStartupFailure);
        Assert.AreEqual(ConnectionState.Failed, model.Connection.State);
        Assert.AreEqual(failure.ErrorCode, model.Connection.ErrorCode);
        Assert.AreEqual(
            "birkin 실행 파일을 찾을 수 없습니다",
            failure.Title);
        Assert.AreEqual(
            "Windows 앱이 birkin 명령을 시작하지 못했습니다.",
            failure.Explanation);
        Assert.AreEqual(
            "Birkin CLI를 설치하거나 실행 파일의 전체 경로를 설정한 다음 다시 시도하세요.",
            failure.RecoveryAction);
    }

    [TestMethod]
    public void StartupFailure_WhenAnnouncementTimesOut_ExposesBoundedTimeoutCode()
    {
        // Given / When
        var failure = StartupFailurePresentation.Create(
            BridgeStartupFailureReason.CliTimedOut);

        // Then
        Assert.AreEqual("E_CLI_TIMEOUT", failure.ErrorCode);
        Assert.IsFalse(string.IsNullOrWhiteSpace(failure.Explanation));
        Assert.IsFalse(string.IsNullOrWhiteSpace(failure.RecoveryAction));
    }

    [TestMethod]
    public void ClearStartupFailure_WhenRetryBegins_RemovesPersistentExplanation()
    {
        // Given
        var context = new DeterministicSynchronizationContext();
        var model = new ShellPresentationModel(context);
        model.PresentStartupFailure(StartupFailurePresentation.Create(
            BridgeStartupFailureReason.CliUnavailable));
        context.RunAll();

        // When
        model.ClearStartupFailure();
        context.RunAll();

        // Then
        Assert.IsNull(model.StartupFailure);
        Assert.IsFalse(model.HasStartupFailure);
    }

    [TestMethod]
    public void StartupFailure_WhenBridgeCrashLoops_ExposesSpecificReason()
    {
        // Given
        var context = new DeterministicSynchronizationContext();
        var model = new ShellPresentationModel(context);
        var failure = StartupFailurePresentation.Create(
            BridgeStartupFailureReason.CliCrashLoop);

        // When
        model.PresentStartupFailure(failure);
        context.RunAll();

        // Then
        Assert.AreSame(failure, model.StartupFailure);
        Assert.IsTrue(model.HasStartupFailure);
        Assert.AreEqual(ConnectionState.Failed, model.Connection.State);
        Assert.AreEqual("E_CLI_CRASH_LOOP", failure.ErrorCode);
        Assert.AreEqual(
            "Birkin CLI가 반복해서 종료되었습니다",
            failure.Title);
        Assert.AreEqual(
            "birkin 명령이 1분 안에 5번 종료되었습니다.",
            failure.Explanation);
        Assert.IsTrue(failure.CanRetry);
    }

    private sealed class DeterministicSynchronizationContext : SynchronizationContext
    {
        private readonly Queue<(SendOrPostCallback Callback, object? State)> _work = new();

        public override void Post(SendOrPostCallback d, object? state) => _work.Enqueue((d, state));

        public void RunAll()
        {
            while (_work.TryDequeue(out var work))
            {
                work.Callback(work.State);
            }
        }
    }
}
