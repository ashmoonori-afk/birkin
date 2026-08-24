using System.ComponentModel;
using Birkin.Native.Shell.Connection;
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
