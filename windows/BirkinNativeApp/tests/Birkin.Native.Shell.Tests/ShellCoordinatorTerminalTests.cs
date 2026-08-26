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

[TestClass]
public sealed partial class ShellCoordinatorTerminalTests
{
    [TestMethod]
    public async Task CreateInputResizeSignalClose_UseReceiptOnlyLeaseAndTypedStateTransitions()
    {
        await using var fixture = await Fixture.CreateAsync(ShellCoordinatorTerminalTestSupport.Commands(
            "terminal.create", "terminal.input", "terminal.resize", "terminal.signal", "terminal.close"));
        fixture.Connection.Enqueue(Receipt(
            "terminal-create-73",
            52,
            Object(
                ("terminal_id", new NativeJsonString("terminal-91")),
                ("lease", new NativeJsonString("transient-lease-510")),
                ("lease_expires_in", new NativeJsonInteger(47)))));

        Assert.IsTrue(await InvokeAsync(
            fixture.Coordinator,
            "CreateTerminalAsync",
            @"C:\workspace\terminal-73",
            CancellationToken.None));
        fixture.Drain();
        AssertState(fixture.Model, "AcceptedPendingProjection");
        AssertNoPublicLease(fixture.Model);
        fixture.Store.ApplyEvent(TerminalEvent(
            52,
            "terminal-create-73",
            "terminal.opened",
            Object(
                ("terminal_id", new NativeJsonString("terminal-91")),
                ("cwd", new NativeJsonString(@"C:\workspace\terminal-73")),
                ("lease", new NativeJsonString("[REDACTED]")),
                ("state", new NativeJsonString("running")),
                ("columns", new NativeJsonInteger(80)),
                ("rows", new NativeJsonInteger(24)))));
        fixture.Drain();
        AssertState(fixture.Model, "Idle");

        fixture.Connection.Enqueue(Receipt("terminal-input-29", 53, Object(
            ("terminal_id", new NativeJsonString("terminal-91")),
            ("input_sequence", new NativeJsonInteger(1)))));
        Assert.IsTrue(await InvokeAsync(
            fixture.Coordinator,
            "SendTerminalInputAsync",
            "terminal-91",
            "echo 한글-日本語\r\n",
            CancellationToken.None));
        AssertPayload(fixture.Connection.Sent[^1], "terminal.input", Object(
            ("terminal_id", new NativeJsonString("terminal-91")),
            ("lease", new NativeJsonString("transient-lease-510")),
            ("sequence", new NativeJsonInteger(1)),
            ("data", new NativeJsonString("echo 한글-日本語\r\n"))));
        fixture.Drain();
        Assert.AreEqual(2L, LongProperty(TerminalWorkflow(fixture.Model), "NextInputSequence"));
        fixture.Store.ApplyEvent(TerminalEvent(53, "terminal-input-29", "terminal.input", Object(
            ("terminal_id", new NativeJsonString("terminal-91")),
            ("sequence", new NativeJsonInteger(1)),
            ("redacted", new NativeJsonBoolean(true)))));

        fixture.Connection.Enqueue(Receipt("terminal-resize-47", 54, Object(
            ("terminal_id", new NativeJsonString("terminal-91")),
            ("columns", new NativeJsonInteger(137)),
            ("rows", new NativeJsonInteger(43)))));
        Assert.IsTrue(await InvokeAsync(
            fixture.Coordinator,
            "ResizeTerminalAsync",
            "terminal-91",
            137L,
            43L,
            CancellationToken.None));
        AssertPayload(fixture.Connection.Sent[^1], "terminal.resize", Object(
            ("terminal_id", new NativeJsonString("terminal-91")),
            ("lease", new NativeJsonString("transient-lease-510")),
            ("columns", new NativeJsonInteger(137)),
            ("rows", new NativeJsonInteger(43))));
        fixture.Store.ApplyEvent(TerminalEvent(54, "terminal-resize-47", "terminal.resized", Object(
            ("terminal_id", new NativeJsonString("terminal-91")),
            ("columns", new NativeJsonInteger(137)),
            ("rows", new NativeJsonInteger(43)))));

        fixture.Connection.Enqueue(Receipt("terminal-signal-19", 55, Object(
            ("terminal_id", new NativeJsonString("terminal-91")),
            ("signal", new NativeJsonString("INT")))));
        Assert.IsTrue(await InvokeAsync(
            fixture.Coordinator,
            "InterruptTerminalAsync",
            "terminal-91",
            CancellationToken.None));
        AssertPayload(fixture.Connection.Sent[^1], "terminal.signal", Object(
            ("terminal_id", new NativeJsonString("terminal-91")),
            ("lease", new NativeJsonString("transient-lease-510")),
            ("signal", new NativeJsonString("INT"))));
        fixture.Store.ApplyEvent(TerminalEvent(55, "terminal-signal-19", "terminal.receipt", Object(
            ("terminal_id", new NativeJsonString("terminal-91")),
            ("signal", new NativeJsonString("INT")),
            ("action", new NativeJsonString("signal")))));

        fixture.Connection.Enqueue(Receipt("terminal-close-83", 56, Object(
            ("terminal_id", new NativeJsonString("terminal-91")),
            ("closed", new NativeJsonBoolean(true)))));
        Assert.IsTrue(await InvokeAsync(
            fixture.Coordinator,
            "CloseTerminalAsync",
            "terminal-91",
            CancellationToken.None));
        AssertPayload(fixture.Connection.Sent[^1], "terminal.close", Object(
            ("terminal_id", new NativeJsonString("terminal-91")),
            ("lease", new NativeJsonString("transient-lease-510"))));
        fixture.Store.ApplyEvent(TerminalEvent(56, "terminal-close-83", "terminal.exited", Object(
            ("terminal_id", new NativeJsonString("terminal-91")),
            ("exit_status", new NativeJsonInteger(73)))));
        fixture.Drain();
        Assert.IsNull(StringProperty(TerminalWorkflow(fixture.Model), "TerminalId"));
        AssertNoPublicLease(fixture.Model);
    }
    [TestMethod]
    public async Task Input_WhenCursorIsStale_PreservesSequenceAndUsesRecoveredCursorOnExplicitRetry()
    {
        await using var fixture = await Fixture.WithTerminalAsync();
        fixture.Connection.Enqueue(Refusal(
            "E_STALE_CURSOR", "terminal-input-29", 83, null, "stale terminal cursor"));

        Assert.IsFalse(await InvokeAsync(
            fixture.Coordinator,
            "SendTerminalInputAsync",
            "terminal-91",
            "first\r\n",
            CancellationToken.None));
        fixture.Drain();
        AssertState(fixture.Model, "Refused");
        Assert.AreEqual(83L, LongProperty(TerminalWorkflow(fixture.Model), "CurrentCursor"));
        Assert.AreEqual(1L, LongProperty(TerminalWorkflow(fixture.Model), "NextInputSequence"));

        fixture.Connection.Enqueue(Receipt("terminal-resize-47", 84, Object(
            ("terminal_id", new NativeJsonString("terminal-91")),
            ("input_sequence", new NativeJsonInteger(1)))));
        Assert.IsTrue(await InvokeAsync(
            fixture.Coordinator,
            "SendTerminalInputAsync",
            "terminal-91",
            "first\r\n",
            CancellationToken.None));
        Assert.AreEqual(83L, fixture.Connection.Sent[^1].ExpectedCursor);
        Assert.AreEqual(1L, Integer(fixture.Connection.Sent[^1].Payload, "sequence"));
    }
    private sealed class Fixture : IAsyncDisposable
    {
        private Fixture(
            TestConnection connection,
            DeterministicSynchronizationContext context,
            NativeProjectionStore store,
            ShellPresentationModel model,
            ShellCoordinator coordinator) =>
            (Connection, Context, Store, Model, Coordinator) =
                (connection, context, store, model, coordinator);

        public TestConnection Connection { get; }
        public DeterministicSynchronizationContext Context { get; }
        public NativeProjectionStore Store { get; }
        public ShellPresentationModel Model { get; }
        public ShellCoordinator Coordinator { get; }

        public void Drain() => Context.RunAll();

        public static async Task<Fixture> CreateAsync(IReadOnlySet<string> commands)
        {
            var store = new NativeProjectionStore();
            var connection = new TestConnection(store, commands);
            var context = new DeterministicSynchronizationContext();
            var model = new ShellPresentationModel(context);
            var ids = new Queue<string>([
                "terminal-create-73", "terminal-input-29", "terminal-resize-47",
                "terminal-signal-19", "terminal-close-83", "terminal-input-47",
            ]);
            var coordinator = new ShellCoordinator(connection, store, model)
            {
                CommandIdFactory = () => ids.Dequeue(),
            };
            await coordinator.ConnectAsync(
                TestBridgeAnnouncement.Json(),
                "0.4.276",
                CancellationToken.None);
            store.ApplySnapshot(
                Snapshot(51),
                new NativeReadyIdentity("session-1", InstanceId, "0.4.276"));
            context.RunAll();
            return new Fixture(connection, context, store, model, coordinator);
        }

        public static async Task<Fixture> WithTerminalAsync()
        {
            var fixture = await CreateAsync(ShellCoordinatorTerminalTestSupport.Commands(
                "terminal.create", "terminal.input", "terminal.resize", "terminal.signal", "terminal.close"));
            fixture.Connection.Enqueue(Receipt("terminal-create-73", 52, Object(
                ("terminal_id", new NativeJsonString("terminal-91")),
                ("lease", new NativeJsonString("transient-lease-510")))));
            Assert.IsTrue(await InvokeAsync(
                fixture.Coordinator,
                "CreateTerminalAsync",
                @"C:\workspace\terminal-73",
                CancellationToken.None));
            fixture.Store.ApplyEvent(TerminalEvent(52, "terminal-create-73", "terminal.opened", Object(
                ("terminal_id", new NativeJsonString("terminal-91")),
                ("state", new NativeJsonString("running")))));
            fixture.Drain();
            return fixture;
        }

        public ValueTask DisposeAsync() => Coordinator.DisposeAsync();
    }

    private sealed class DeterministicSynchronizationContext : SynchronizationContext
    {
        private readonly Queue<(SendOrPostCallback Callback, object? State)> _work = new();
        public override void Post(SendOrPostCallback d, object? state) => _work.Enqueue((d, state));
        public void RunAll()
        {
            while (_work.TryDequeue(out var work)) work.Callback(work.State);
        }
    }
}
