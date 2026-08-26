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
    public async Task CanonicalOpenedCursor_SettlesNextTerminalInputExpectedCursor()
    {
        await using var fixture = await Fixture.CreateAsync(ShellCoordinatorTerminalTestSupport.Commands("terminal.create", "terminal.input"));
        fixture.Connection.Enqueue(Receipt("terminal-create-73", 52, Object(
            ("terminal_id", new NativeJsonString("terminal-cursor-53")),
            ("lease", new NativeJsonString("transient-cursor-lease")))));
        Assert.IsTrue(await InvokeAsync(fixture.Coordinator, "CreateTerminalAsync",
            StringProperty(TerminalWorkflow(fixture.Model), "WorkspaceCwd")!, CancellationToken.None));
        fixture.Store.ApplyEvent(TerminalEvent(52, "terminal-create-73", "command.completed", Object()));
        fixture.Store.ApplyEvent(TerminalEvent(53, "terminal-create-73", "terminal.opened", Object(
            ("terminal_id", new NativeJsonString("terminal-cursor-53")),
            ("state", new NativeJsonString("running")))));
        fixture.Drain();

        fixture.Connection.Enqueue(Receipt("terminal-input-29", 54, Object(
            ("terminal_id", new NativeJsonString("terminal-cursor-53")),
            ("input_sequence", new NativeJsonInteger(1)))));
        Assert.IsTrue(await InvokeAsync(fixture.Coordinator, "SendTerminalInputAsync",
            "terminal-cursor-53", "echo cursor\r\n", CancellationToken.None));
        Assert.AreEqual(53L, fixture.Connection.Sent[^1].ExpectedCursor);
    }
    [TestMethod]
    public async Task CanonicalEventBeforeCreateReceipt_RetainsTransientAuthorityAndSettlesActiveTerminal()
    {
        // Given
        var store = new NativeProjectionStore();
        var connection = new TestConnection(store, ShellCoordinatorTerminalTestSupport.Commands(
            "terminal.create", "terminal.input", "terminal.resize", "terminal.signal", "terminal.close"));
        var context = new DeterministicSynchronizationContext();
        var model = new ShellPresentationModel(context);
        var commandIds = new Queue<string>(["terminal-event-first-create-73", "terminal-event-first-input-29"]);
        await using var coordinator = new ShellCoordinator(connection, store, model)
        {
            CommandIdFactory = () => commandIds.Dequeue(),
        };
        await coordinator.ConnectAsync(TestBridgeAnnouncement.Json(), "0.4.276", CancellationToken.None);
        store.ApplySnapshot(Snapshot(6), new NativeReadyIdentity("session-1", InstanceId, "0.4.276"));
        context.RunAll();
        connection.Enqueue(new NativeEnvelope(
            NativeMessageKind.Receipt,
            "receipt-terminal-event-first-create-73",
            Object(
                ("protocol_version", new NativeJsonInteger(1)),
                ("command_id", new NativeJsonString("terminal-event-first-create-73")),
                ("session_id", new NativeJsonString("session-1")),
                ("actor_id", new NativeJsonString("windows:terminal")),
                ("accepted_cursor", new NativeJsonInteger(6)),
                ("state", new NativeJsonString("completed")),
                ("result_event_cursor", new NativeJsonInteger(11)),
                ("duplicate", new NativeJsonBoolean(false)),
                ("outcome", new NativeJsonString("accepted")),
                ("result", Object(
                    ("terminal_id", new NativeJsonString("terminal-event-first-91")),
                    ("lease", new NativeJsonString("transient-event-first-lease-510")))))));
        connection.BeforeResult = request =>
        {
            store.ApplyEvent(TerminalEvent(7, request.CommandId, "terminal.opened", Object(
                ("terminal_id", new NativeJsonString("terminal-event-first-91")),
                ("cwd", new NativeJsonString(@"C:\workspace\event-first")),
                ("state", new NativeJsonString("running")))));
            store.ApplyEvent(TerminalEvent(8, request.CommandId, "terminal.output", Object(
                ("terminal_id", new NativeJsonString("terminal-event-first-91")),
                ("sequence", new NativeJsonInteger(1)),
                ("data", new NativeJsonString("ready")))));
            store.ApplyEvent(TerminalEvent(9, request.CommandId, "terminal.resized", Object(
                ("terminal_id", new NativeJsonString("terminal-event-first-91")),
                ("columns", new NativeJsonInteger(100)),
                ("rows", new NativeJsonInteger(30)))));
            store.ApplyEvent(TerminalEvent(10, request.CommandId, "terminal.receipt", Object(
                ("terminal_id", new NativeJsonString("terminal-event-first-91")),
                ("action", new NativeJsonString("create")))));
            store.ApplyEvent(TerminalEvent(11, request.CommandId, "command.completed", Object()));
        };

        // When
        Assert.IsTrue(await InvokeAsync(
            coordinator,
            "CreateTerminalAsync",
            @"C:\workspace\event-first",
            CancellationToken.None));
        connection.BeforeResult = null;
        context.RunAll();

        // Then
        var workflow = TerminalWorkflow(model);
        AssertState(model, "Idle");
        Assert.AreEqual(11L, LongProperty(workflow, "CurrentCursor"));
        Assert.IsNull(LongProperty(workflow, "AcceptedCursor"));
        Assert.AreEqual("terminal-event-first-91", StringProperty(workflow, "TerminalId"));
        AssertAvailability(model, "CreateAvailability", false, "E_TERMINAL_ACTIVE");
        var mutations = Property(workflow, "MutationAvailability")!;
        foreach (var name in new[] { "Input", "Resize", "Interrupt", "Close" })
        {
            Assert.AreEqual(true, Property(Property(mutations, name)!, "IsEnabled"), name);
        }

        connection.Enqueue(Receipt("terminal-event-first-input-29", 12, Object(
            ("terminal_id", new NativeJsonString("terminal-event-first-91")),
            ("input_sequence", new NativeJsonInteger(1)))));
        Assert.IsTrue(await InvokeAsync(
            coordinator,
            "SendTerminalInputAsync",
            "terminal-event-first-91",
            "echo event-first\r\n",
            CancellationToken.None));
        Assert.AreEqual(11L, connection.Sent[^1].ExpectedCursor);
        Assert.AreEqual(1L, Integer(connection.Sent[^1].Payload, "sequence"));
        Assert.AreEqual(2, connection.Sent.Count);
        store.ApplyEvent(TerminalEvent(12, "terminal-event-first-input-29", "terminal.input", Object(
            ("terminal_id", new NativeJsonString("terminal-event-first-91")),
            ("sequence", new NativeJsonInteger(1)),
            ("redacted", new NativeJsonBoolean(true)))));
        store.ApplyEvent(TerminalEvent(13, "terminal-exit-83", "terminal.exited", Object(
            ("terminal_id", new NativeJsonString("terminal-event-first-91")),
            ("exit_status", new NativeJsonInteger(0)))));
        context.RunAll();
        Assert.IsNull(StringProperty(TerminalWorkflow(model), "TerminalId"));
        AssertAvailability(model, "CreateAvailability", true, null);

        await coordinator.ConnectAsync(TestBridgeAnnouncement.Json(), "0.4.276", CancellationToken.None);
        store.ApplySnapshot(
            Snapshot(14, Terminal("terminal-event-first-91", "read-only", "running", true)),
            new NativeReadyIdentity("session-1", InstanceId, "0.4.276"));
        context.RunAll();
        Assert.AreEqual(false, Property(
            Property(Property(TerminalWorkflow(model), "MutationAvailability")!, "Input")!,
            "IsEnabled"));
    }
}
