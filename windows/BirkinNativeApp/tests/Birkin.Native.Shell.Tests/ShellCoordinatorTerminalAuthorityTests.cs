using System.Reflection;
using System.Runtime.ExceptionServices;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;
using static Birkin.Native.Shell.Tests.ShellCoordinatorTerminalTestSupport;

namespace Birkin.Native.Shell.Tests;

public sealed partial class ShellCoordinatorTerminalTests
{
    [TestMethod]
    public async Task WorkspaceCwd_ComesOnlyFromValidatedAnnouncementAndClearsWithAuthority()
    {
        var store = new NativeProjectionStore();
        var connection = new TestConnection(store, ShellCoordinatorTerminalTestSupport.Commands("terminal.create"));
        var context = new DeterministicSynchronizationContext();
        var model = new ShellPresentationModel(context);
        await using var coordinator = new ShellCoordinator(connection, store, model)
        {
            CommandIdFactory = () => "terminal-create-cwd-73",
        };
        Assert.IsNull(StringProperty(TerminalWorkflow(model), "WorkspaceCwd"));

        var announcementJson = TestBridgeAnnouncement.Json();
        var expectedCwd = BridgeAnnouncement.Parse(announcementJson).Root;
        await coordinator.ConnectAsync(announcementJson, "0.4.276", CancellationToken.None);
        store.ApplySnapshot(
            Snapshot(51),
            new NativeReadyIdentity("session-1", InstanceId, "0.4.276"));
        context.RunAll();
        Assert.AreEqual(expectedCwd, StringProperty(TerminalWorkflow(model), "WorkspaceCwd"));

        connection.Enqueue(Receipt("terminal-create-cwd-73", 52, Object(
            ("terminal_id", new NativeJsonString("terminal-cwd-73")),
            ("lease", new NativeJsonString("transient-cwd-lease-73")))));
        Assert.IsTrue(await InvokeAsync(
            coordinator,
            "CreateTerminalAsync",
            expectedCwd,
            CancellationToken.None));
        Assert.AreEqual(expectedCwd, String(connection.Sent.Single().Payload, "cwd"));

        store.MarkMutationAuthorityUnavailable();
        context.RunAll();
        Assert.IsNull(StringProperty(TerminalWorkflow(model), "WorkspaceCwd"));
    }
    [TestMethod]
    public async Task Reconnect_ClearsTransientLeaseAndLeavesProjectedTerminalReadOnly()
    {
        await using var fixture = await Fixture.WithTerminalAsync();
        var sentBeforeReconnect = fixture.Connection.Sent.Count;

        await fixture.Coordinator.ConnectAsync(
            TestBridgeAnnouncement.Json(),
            "0.4.276",
            CancellationToken.None);
        fixture.Store.ApplySnapshot(Snapshot(61, Terminal(
            "terminal-91", "preserved display", "running", true)),
            new NativeReadyIdentity("session-1", InstanceId, "0.4.276"));
        fixture.Drain();

        Assert.IsFalse(await InvokeAsync(
            fixture.Coordinator,
            "SendTerminalInputAsync",
            "terminal-91",
            "must not send\r\n",
            CancellationToken.None));
        Assert.AreEqual(sentBeforeReconnect, fixture.Connection.Sent.Count);
        Assert.IsTrue((bool)Property(fixture.Model.Workspace!.Terminal, "IsReadOnly")!);
        Assert.AreEqual("preserved display", StringProperty(fixture.Model.Workspace.Terminal, "Display"));
        AssertNoPublicLease(fixture.Model);
    }
}
