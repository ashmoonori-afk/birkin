using System.Collections.Concurrent;
using System.Reflection;
using System.Runtime.ExceptionServices;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests;

[TestClass]
public sealed partial class ShellCoordinatorConcurrencyTests
{
    private const string InstanceId = "0123456789abcdef0123456789abcdef";

    [TestMethod]
    public async Task ConcurrentDraftEditAndBackgroundConnectionTransition_PreserveBothChanges()
    {
        var authorityRead = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var releaseAuthority = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var connection = new ControlledConnection(new NativeProjectionStore());
        connection.ArmAuthorityBarrier(authorityRead, releaseAuthority);
        var context = new ConcurrentSynchronizationContext();
        var model = new ShellPresentationModel(context);
        await using var coordinator = new ShellCoordinator(connection, connection.Store, model);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));

        var connecting = Task.Run(() => coordinator.ConnectAsync(
            AnnouncementJson(), "0.4.276", deadline.Token), deadline.Token);
        await authorityRead.Task.WaitAsync(deadline.Token);
        coordinator.SetConversationDraft("draft written on UI thread");
        releaseAuthority.TrySetResult();
        await connecting;
        context.RunAll();

        Assert.AreEqual(ConnectionState.Subscribing, model.Connection.State);
        Assert.AreEqual("draft written on UI thread", model.OfficeWorkflow.Draft);
    }

    [TestMethod]
    public async Task CanonicalProjectionThenAuthorityRevocationWhileReceiptPending_LeavesMutationsDisabled()
    {
        await using var fixture = await Fixture.CreateAsync();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        fixture.Coordinator.SetConversationDraft("submitted draft");
        var submission = fixture.Coordinator.SendConversationAsync(deadline.Token);
        await fixture.Connection.SendEntered.Task.WaitAsync(deadline.Token);

        var authorityRead = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var releaseAuthority = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        fixture.Connection.ArmAuthorityBarrier(authorityRead, releaseAuthority);
        var canonical = Task.Run(
            () => fixture.Store.ApplyEvent(Event(5, "command-1", "projected")),
            deadline.Token);
        await authorityRead.Task.WaitAsync(deadline.Token);
        await Task.Run(fixture.Store.MarkMutationAuthorityUnavailable, deadline.Token);
        releaseAuthority.TrySetResult();
        await canonical;
        fixture.Connection.CompleteReceipt(Receipt("command-1", 5));
        Assert.IsTrue(await submission);
        fixture.DrainPresentation();

        Assert.AreEqual(WorkflowCommandState.Idle, fixture.Model.OfficeWorkflow.CommandState);
        Assert.IsFalse(fixture.Model.OfficeWorkflow.Availability.ConversationSend.IsEnabled);
        Assert.IsNotNull(fixture.Model.OfficeWorkflow.Availability.ConversationSend.DisabledReason);
    }

    [TestMethod]
    public async Task ReceiptAndCanonicalEventForSubmittedDraft_DoNotOverwriteNewerDraft()
    {
        await using var fixture = await Fixture.CreateAsync();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        fixture.Coordinator.SetConversationDraft("submitted draft");
        var submission = fixture.Coordinator.SendConversationAsync(deadline.Token);
        await fixture.Connection.SendEntered.Task.WaitAsync(deadline.Token);

        fixture.Coordinator.SetConversationDraft("newer draft");
        fixture.Connection.CompleteReceipt(Receipt("command-1", 5));
        Assert.IsTrue(await submission);
        fixture.Store.ApplyEvent(Event(5, "command-1", "projected"));
        fixture.DrainPresentation();

        Assert.AreEqual("newer draft", fixture.Model.OfficeWorkflow.Draft);
        Assert.AreEqual(WorkflowCommandState.Idle, fixture.Model.OfficeWorkflow.CommandState);
    }

    [TestMethod]
    public async Task ReentrantPresenter_CanMutateCoordinatorWithoutWaitingForStateLock()
    {
        ShellCoordinator? coordinator = null;
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var context = new ReentrantSynchronizationContext(() =>
            Task.Run(() => coordinator!.SetConversationDraft("reentrant"), deadline.Token));
        var connection = new ControlledConnection(new NativeProjectionStore());
        var model = new ShellPresentationModel(context);
        await using (coordinator = new ShellCoordinator(connection, connection.Store, model))
        {
            coordinator.SetConversationDraft("outer");
        }

        Assert.IsTrue(context.ReentrantMutationCompleted);
    }

    [TestMethod]
    public async Task CanonicalPresentationSnapshot_ContainsMatchingProjectionAndWorkflowState()
    {
        var context = new ImmediateSynchronizationContext();
        await using var fixture = await Fixture.CreateAsync(context);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        fixture.Coordinator.SetConversationDraft("submitted draft");
        var submission = fixture.Coordinator.SendConversationAsync(deadline.Token);
        await fixture.Connection.SendEntered.Task.WaitAsync(deadline.Token);
        fixture.Connection.CompleteReceipt(Receipt("command-1", 5));
        Assert.IsTrue(await submission);

        OfficeWorkflowPresentation? workflowSeenWithProjection = null;
        fixture.Model.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(ShellPresentationModel.Workspace)
                && fixture.Model.Workspace?.Cursor == 5)
            {
                workflowSeenWithProjection = fixture.Model.OfficeWorkflow;
            }
        };
        fixture.Store.ApplyEvent(Event(5, "command-1", "projected"));

        Assert.IsNotNull(workflowSeenWithProjection);
        Assert.AreEqual(WorkflowCommandState.Idle, workflowSeenWithProjection.CommandState);
        Assert.IsTrue(workflowSeenWithProjection.Availability.ConversationSend.IsEnabled);
    }

}
