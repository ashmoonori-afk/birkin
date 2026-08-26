using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Threading;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Birkin.Native.Protocol.Framing;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
[TestCategory("Terminal")]
public sealed class TerminalViewAccessibilityTests
{
    private static readonly IReadOnlySet<string> TerminalCommands = new HashSet<string>(
        ["terminal.create", "terminal.input", "terminal.resize", "terminal.signal", "terminal.close"],
        StringComparer.Ordinal);

    [DataTestMethod]
    [DataRow(1500, 940)]
    [DataRow(1100, 700)]
    public async Task Output_ExposesSafeReadOnlyTextAndValuePatternsInsideContainedViewport(int width, int height)
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            const string display = "CONPTY_OK\n한글-日本語\n[workspace]>";
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync(
                advertisedCommands: TerminalCommands,
                terminals: [Terminal(display)]);
            var window = new MainWindow(fixture.Model, fixture.Coordinator)
            {
                Width = width,
                Height = height,
                WindowStartupLocation = WindowStartupLocation.Manual,
                Left = 0,
                Top = 0,
            };
            window.Show();
            try
            {
                await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.Render);
                window.UpdateLayout();
                var primaryScroll = OfficeWorkflowViewHarness.Find<ScrollViewer>(window, "primary.scroll");
                var outputControl = OfficeWorkflowViewHarness.Find<TextBox>(window, "terminal.output");
                Assert.IsTrue(outputControl.IsReadOnly);
                outputControl.BringIntoView();
                await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.Render);
                window.UpdateLayout();

                // When
                var root = AutomationElement.FromHandle(new WindowInteropHelper(window).Handle);
                var output = root.FindFirst(TreeScope.Descendants,
                    new PropertyCondition(AutomationElement.AutomationIdProperty, "terminal.output"));
                Assert.IsNotNull(output);
                var hasText = output.TryGetCurrentPattern(TextPattern.Pattern, out var textObject);
                var hasValue = output.TryGetCurrentPattern(ValuePattern.Pattern, out var valueObject);

                // Then
                Assert.IsTrue(hasText, "terminal output must support TextPattern");
                Assert.IsTrue(hasValue, "terminal output must support ValuePattern");
                var text = ((TextPattern)textObject).DocumentRange.GetText(-1).TrimEnd('\r', '\n');
                var value = (ValuePattern)valueObject;
                Assert.AreEqual(display, text);
                Assert.AreEqual(text, value.Current.Value);
                Assert.IsTrue(value.Current.IsReadOnly);
                Assert.AreEqual("Terminal output", output.Current.Name);
                Assert.IsTrue(output.Current.BoundingRectangle.Height >= 96,
                    $"output viewport was {output.Current.BoundingRectangle.Height}px at {width}x{height}");
                Assert.IsTrue(primaryScroll.VerticalOffset >= 0);
                var landmark = root.FindFirst(TreeScope.Descendants,
                    new PropertyCondition(AutomationElement.AutomationIdProperty, "terminal.landmark"));
                Assert.IsNotNull(landmark);
                AssertContains(landmark.Current.BoundingRectangle, output.Current.BoundingRectangle);
                foreach (var id in new[] { "terminal.input", "terminal.create", "terminal.send", "terminal.close" })
                {
                    var child = root.FindFirst(TreeScope.Descendants,
                        new PropertyCondition(AutomationElement.AutomationIdProperty, id));
                    Assert.IsNotNull(child, id);
                    Assert.IsTrue(child.Current.BoundingRectangle.IntersectsWith(landmark.Current.BoundingRectangle), id);
                }
            }
            finally
            {
                window.Close();
            }
        });
    }

    [TestMethod]
    public async Task AvailabilityAndReadOnlyState_GateCreateAndEveryLeaseBackedControl()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var disabled = await OfficeWorkflowViewHarness.CreateAsync(advertisedCommands: new HashSet<string>());
            var disabledView = new PrimaryColumnView();
            disabledView.AttachWorkflow(disabled.Model, disabled.Coordinator);
            OfficeWorkflowViewHarness.Layout(disabledView);

            // When / Then
            Assert.IsFalse(OfficeWorkflowViewHarness.Find<Button>(disabledView, "terminal.create").IsEnabled);
            await using var projected = await OfficeWorkflowViewHarness.CreateAsync(
                advertisedCommands: TerminalCommands,
                terminals: [Terminal("projected read-only output")]);
            var projectedView = new PrimaryColumnView();
            projectedView.AttachWorkflow(projected.Model, projected.Coordinator);
            OfficeWorkflowViewHarness.Layout(projectedView);
            Assert.IsTrue(OfficeWorkflowViewHarness.Find<Button>(projectedView, "terminal.create").IsEnabled);
            foreach (var id in new[] { "terminal.input", "terminal.send", "terminal.resize", "terminal.interrupt", "terminal.close" })
                Assert.IsFalse(OfficeWorkflowViewHarness.Find<Control>(projectedView, id).IsEnabled, id);
            StringAssert.Contains(OfficeWorkflowViewHarness.Find<TextBlock>(projectedView, "terminal.guidance").Text, "read-only");
        });
    }

    [TestMethod]
    public async Task Controls_ExposeStableAutomationNamesWithoutMachineAuthority()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync(advertisedCommands: TerminalCommands);
            var view = new PrimaryColumnView();
            view.AttachWorkflow(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);

            // When / Then
            var expected = new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["terminal.create"] = "Create terminal", ["terminal.input"] = "Terminal input",
                ["terminal.send"] = "Send terminal input", ["terminal.columns"] = "Terminal columns",
                ["terminal.rows"] = "Terminal rows", ["terminal.resize"] = "Resize terminal",
                ["terminal.interrupt"] = "Interrupt terminal", ["terminal.close"] = "Close terminal",
                ["terminal.output"] = "Terminal output",
            };
            foreach (var pair in expected)
            {
                var elements = OfficeWorkflowViewHarness.FindAll<FrameworkElement>(view, pair.Key);
                var element = pair.Key == "terminal.output"
                    ? elements.Single(item => item is TextBox)
                    : elements.Single();
                Assert.AreEqual(pair.Value, AutomationProperties.GetName(element), pair.Key);
            }
            Assert.AreEqual(AutomationLiveSetting.Polite,
                AutomationProperties.GetLiveSetting(OfficeWorkflowViewHarness.Find<TextBox>(view, "terminal.output")));
        });
    }

    private static NativeJsonObject Terminal(string display) => OfficeWorkflowViewHarness.JsonObject(
        ("terminal_id", new NativeJsonString("terminal-accessibility")),
        ("cwd", new NativeJsonString(@"C:\workspace")),
        ("screen", new NativeJsonString(display.Replace("\n", "\r\n", StringComparison.Ordinal))),
        ("display", new NativeJsonString("stale")),
        ("output_sequence", new NativeJsonInteger(73)),
        ("state", new NativeJsonString("running")),
        ("exit_status", NativeJsonNull.Value),
        ("columns", new NativeJsonInteger(100)),
        ("rows", new NativeJsonInteger(30)),
        ("read_only", new NativeJsonBoolean(true)));

    private static void AssertContains(Rect outer, Rect inner) =>
        Assert.IsTrue(inner.Left >= outer.Left && inner.Top >= outer.Top
            && inner.Right <= outer.Right + 1 && inner.Bottom <= outer.Bottom + 1,
            $"child {inner} escaped terminal landmark {outer}");
}
