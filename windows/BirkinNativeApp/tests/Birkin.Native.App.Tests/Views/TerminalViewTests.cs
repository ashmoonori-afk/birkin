using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
[TestCategory("Terminal")]
public sealed class TerminalViewTests
{
    private static readonly IReadOnlySet<string> TerminalCommands = new HashSet<string>(
        ["terminal.create", "terminal.input", "terminal.resize", "terminal.signal", "terminal.close"],
        StringComparer.Ordinal);

    [TestMethod]
    public async Task CreateInputResizeInterruptClose_DispatchExactUiIntentThroughCoordinator()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        var test = await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync(advertisedCommands: TerminalCommands);
            var view = new PrimaryColumnView();
            view.AttachWorkflow(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            fixture.EnqueueCommandResult(OfficeWorkflowViewHarness.JsonObject(
                ("terminal_id", new NativeJsonString("terminal-ui-73")),
                ("lease", new NativeJsonString("test-only-transient-authority-510"))));
            var createRequest = SubscribeNextCommand(fixture);

            // When
            Find<Button>(view, "terminal.create").RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            var created = await createRequest.WaitAsync(deadline.Token);
            fixture.ApplyCanonical(created.CommandId, "terminal.opened", OfficeWorkflowViewHarness.JsonObject(
                ("terminal_id", new NativeJsonString("terminal-ui-73")),
                ("cwd", new NativeJsonString(Environment.CurrentDirectory)),
                ("state", new NativeJsonString("running")),
                ("columns", new NativeJsonInteger(80)),
                ("rows", new NativeJsonInteger(24))));
            await view.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.DataBind);

            // Then
            Assert.AreEqual("terminal.create", created.CommandType);
            Assert.AreEqual(@"C:\root", String(created.Payload, "cwd"));
            Assert.IsFalse(Find<Button>(view, "terminal.create").IsEnabled);
            foreach (var id in new[] { "terminal.input", "terminal.send", "terminal.resize", "terminal.interrupt", "terminal.close" })
                Assert.IsTrue(Find<Control>(view, id).IsEnabled, id);
            Assert.AreEqual(Visibility.Collapsed, Find<TextBlock>(view, "terminal.guidance").Visibility);

            var input = Find<TextBox>(view, "terminal.input");
            input.Text = "echo 한글-日本語";
            fixture.EnqueueCommandResult(OfficeWorkflowViewHarness.JsonObject(
                ("terminal_id", new NativeJsonString("terminal-ui-73")),
                ("input_sequence", new NativeJsonInteger(1))));
            var inputRequest = SubscribeNextCommand(fixture);
            Find<Button>(view, "terminal.send").RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            var sentInput = await inputRequest.WaitAsync(deadline.Token);
            Assert.AreEqual("terminal.input", sentInput.CommandType);
            Assert.AreEqual("echo 한글-日本語\r\n", String(sentInput.Payload, "data"));
            fixture.ApplyCanonical(sentInput.CommandId, "terminal.input", OfficeWorkflowViewHarness.JsonObject(
                ("terminal_id", new NativeJsonString("terminal-ui-73")),
                ("sequence", new NativeJsonInteger(1)),
                ("redacted", new NativeJsonBoolean(true))));

            Find<TextBox>(view, "terminal.columns").Text = "100";
            Find<TextBox>(view, "terminal.rows").Text = "30";
            await AssertClickCommandAsync(fixture, view, "terminal.resize", "terminal.resize", "terminal.resized", deadline.Token);
            await AssertClickCommandAsync(fixture, view, "terminal.interrupt", "terminal.signal", "terminal.receipt", deadline.Token);
            await AssertClickCommandAsync(fixture, view, "terminal.close", "terminal.close", "terminal.exited", deadline.Token);
        });
        await test.WaitAsync(deadline.Token);
    }

    private static Task<NativeCommandRequest> SubscribeNextCommand(OfficeWorkflowViewHarness fixture)
    {
        var observed = new TaskCompletionSource<NativeCommandRequest>(TaskCreationOptions.RunContinuationsAsynchronously);
        fixture.Connection.CommandSent += Sent;
        return observed.Task;
        void Sent(NativeCommandRequest request)
        {
            fixture.Connection.CommandSent -= Sent;
            observed.TrySetResult(request);
        }
    }

    private static async Task AssertClickCommandAsync(
        OfficeWorkflowViewHarness fixture,
        DependencyObject root,
        string automationId,
        string expectedCommand,
        string projectedEvent,
        CancellationToken cancellationToken)
    {
        fixture.EnqueueCommandResult(OfficeWorkflowViewHarness.JsonObject(
            ("terminal_id", new NativeJsonString("terminal-ui-73"))));
        var observed = SubscribeNextCommand(fixture);
        Find<Button>(root, automationId).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        var request = await observed.WaitAsync(cancellationToken);
        Assert.AreEqual(expectedCommand, request.CommandType);
        var payload = projectedEvent switch
        {
            "terminal.resized" => OfficeWorkflowViewHarness.JsonObject(
                ("terminal_id", new NativeJsonString("terminal-ui-73")),
                ("columns", new NativeJsonInteger(100)),
                ("rows", new NativeJsonInteger(30))),
            "terminal.receipt" => OfficeWorkflowViewHarness.JsonObject(
                ("terminal_id", new NativeJsonString("terminal-ui-73")),
                ("action", new NativeJsonString("signal")),
                ("signal", new NativeJsonString("INT"))),
            _ => OfficeWorkflowViewHarness.JsonObject(
                ("terminal_id", new NativeJsonString("terminal-ui-73")),
                ("exit_status", new NativeJsonInteger(0))),
        };
        fixture.ApplyCanonical(request.CommandId, projectedEvent, payload);
    }

    private static T Find<T>(DependencyObject root, string id) where T : DependencyObject =>
        OfficeWorkflowViewHarness.FindAll<T>(root, id).SingleOrDefault()
        ?? throw new AssertFailedException($"Missing WPF terminal binding: {id}");

    private static string String(NativeJsonObject value, string key) =>
        value[key] is NativeJsonString text
            ? text.Value
            : throw new AssertFailedException($"{key} must be a string");
}
