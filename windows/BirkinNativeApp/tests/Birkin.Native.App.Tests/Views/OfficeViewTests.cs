using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Birkin.Native.Protocol.Framing;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class OfficeViewTests
{
    [TestMethod]
    public async Task Create_WhenAdvertised_SubmitsExplicitDocumentValuesOnce()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new OfficeView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            OfficeWorkflowViewHarness.Find<TextBox>(view, "office.output-name").Text = "comparison-report.docx";
            OfficeWorkflowViewHarness.Find<TextBox>(view, "office.content").Text = "BIRKIN_P3_03_DOCUMENT_SENTINEL";
            var create = OfficeWorkflowViewHarness.Find<Button>(view, "office.create");

            // When
            create.RaiseEvent(new System.Windows.RoutedEventArgs(Button.ClickEvent));

            // Then
            Assert.AreEqual(1, fixture.Connection.Sent.Count);
            Assert.AreEqual("office.create", fixture.Connection.Sent[0].CommandType);
            Assert.AreEqual("comparison-report.docx", ((NativeJsonString)fixture.Connection.Sent[0].Payload["output_name"]!).Value);
            Assert.AreEqual("Create office document", AutomationProperties.GetName(create));
        });
    }

    [TestMethod]
    public async Task MainWindow_WhenWorkflowIsAttached_PreservesShellRegionsAndContextualControls()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        // When
        var automationIds = await sta.InvokeAsync(() =>
        {
            var fixture = OfficeWorkflowViewHarness.CreateAsync().GetAwaiter().GetResult();
            var window = new MainWindow(fixture.Model, fixture.Coordinator);
            var shell = (WorkspaceSnapshotView)window.Content;
            OfficeWorkflowViewHarness.Layout(shell, 1500, 940);
            var ids = new[]
            {
                "navigation.sessions", "working-memory.landmark", "conversation.stream",
                "terminal.landmark", "approvals.landmark", "activity.landmark",
                "browser.landmark", "office.landmark", "conversation.send",
                "office.import-panel", "approval.approve", "office.new-panel", "diff.landmark",
            };
            var result = ids.Select(id => AutomationProperties.GetAutomationId(
                OfficeWorkflowViewHarness.Find<FrameworkElement>(shell, id))).ToArray();
            window.Close();
            fixture.DisposeAsync().AsTask().GetAwaiter().GetResult();
            return result;
        });

        // Then
        CollectionAssert.AreEqual(
            new[]
            {
                "navigation.sessions", "working-memory.landmark", "conversation.stream",
                "terminal.landmark", "approvals.landmark", "activity.landmark",
                "browser.landmark", "office.landmark", "conversation.send",
                "office.import-panel", "approval.approve", "office.new-panel", "diff.landmark",
            },
            automationIds);
    }

    [DataTestMethod]
    [DataRow(1500, 940)]
    [DataRow(1100, 700)]
    public async Task ContextRail_WhenWindowIsConstrained_ScrollsCompleteOfficeActionAboveStatus(int width, int height)
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        // When / Then
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
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
                var outer = OfficeWorkflowViewHarness.Find<ScrollViewer>(window, "context.scroll");
                var landmarks = new[] { "approvals.landmark", "activity.landmark", "browser.landmark", "office.landmark" }
                    .Select(id => OfficeWorkflowViewHarness.Find<FrameworkElement>(window, id)).ToArray();
                var viewport = new Rect(new Point(), outer.RenderSize);
                var previousBottom = double.NegativeInfinity;
                foreach (var landmark in landmarks)
                {
                    var bounds = landmark.TransformToAncestor(outer).TransformBounds(new Rect(new Point(), landmark.RenderSize));
                    Assert.IsTrue(bounds.Top >= -1 && bounds.Bottom <= viewport.Bottom + 1,
                        $"{AutomationProperties.GetAutomationId(landmark)} is not contained at {width}x{height}: {bounds}");
                    Assert.IsTrue(bounds.Top >= previousBottom - 1, "context landmark order changed");
                    previousBottom = bounds.Bottom;
                }
                Assert.AreEqual(0d, outer.VerticalOffset, 0.1, "outer context rail must not scroll at target sizes");

                var inner = OfficeWorkflowViewHarness.Find<ScrollViewer>(window, "office.workflow-scroll");
                OfficeWorkflowViewHarness.Find<Expander>(window, "office.new-panel").IsExpanded = true;
                window.UpdateLayout();
                var action = OfficeWorkflowViewHarness.Find<Button>(window, "office.create");
                action.BringIntoView();
                await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.Background);
                var actionBounds = action.TransformToAncestor(inner).TransformBounds(new Rect(new Point(), action.RenderSize));
                Assert.IsTrue(actionBounds.Top >= -1 && actionBounds.Bottom <= inner.ActualHeight + 1,
                    $"Office action is unreachable in inner scroll: {actionBounds}, viewport={inner.ActualHeight}");
                Assert.AreEqual(0d, outer.VerticalOffset, 0.1, "Office inner scroll must not move context rail");
            }
            finally
            {
                window.Close();
            }
        });
    }

    [TestMethod]
    public async Task ActivityRows_ExposeSafeAutomationNamesWithoutRecordMetadata()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        // When / Then
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var window = new MainWindow(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(window);
            var items = OfficeWorkflowViewHarness.Find<ItemsControl>(window, "activity.items");
            var presenters = OfficeWorkflowViewHarness.All<ContentPresenter>(items).Where(p => p.Content is not null).ToArray();
            Assert.IsTrue(presenters.Length > 0, "activity fixture must produce a row");
            foreach (var presenter in presenters)
            {
                var name = AutomationProperties.GetName(presenter);
                Assert.AreEqual("Activity entry", name);
                AssertSafeName(name);
            }
            window.Close();
        });
    }

    [TestMethod]
    public async Task NewDocumentExpander_WhenFocused_UsesVisibleHeaderChrome()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        // When / Then
        await sta.InvokeAsync(() =>
        {
            var fixture = OfficeWorkflowViewHarness.CreateAsync().GetAwaiter().GetResult();
            var window = new MainWindow(fixture.Model, fixture.Coordinator);
            window.Show();
            try
            {
                window.Dispatcher.Invoke(() => { }, DispatcherPriority.Render);
                var expander = OfficeWorkflowViewHarness.Find<Expander>(window, "office.new-panel");
                var header = FindNamedBorder(expander, "OfficeNewHeader");
                Assert.IsNotNull(header);
                Assert.AreEqual(new Thickness(1), header.BorderThickness);
                Assert.AreEqual(Colors.Transparent, ((SolidColorBrush)header.BorderBrush).Color);
                Assert.IsTrue(expander.Focus());
                window.UpdateLayout();
                Assert.AreSame(expander, Keyboard.FocusedElement);
                Assert.AreEqual(new Thickness(2), header.BorderThickness);
                Assert.AreEqual(Color.FromRgb(0xE2, 0xA4, 0x4F), ((SolidColorBrush)header.BorderBrush).Color);
                Assert.AreEqual(Color.FromRgb(0x1A, 0x1C, 0x1D), ((SolidColorBrush)header.Background).Color);
            }
            finally
            {
                window.Close();
                fixture.DisposeAsync().AsTask().GetAwaiter().GetResult();
            }
            return true;
        });
    }

    private static Border? FindNamedBorder(DependencyObject root, string name)
    {
        for (var index = 0; index < VisualTreeHelper.GetChildrenCount(root); index++)
        {
            var child = VisualTreeHelper.GetChild(root, index);
            if (child is Border border && border.Name == name) return border;
            var match = FindNamedBorder(child, name);
            if (match is not null) return match;
        }
        return null;
    }

    private static void AssertSafeName(string name)
    {
        Assert.IsFalse(System.Text.RegularExpressions.Regex.IsMatch(name, "[0-9a-f]{32}", System.Text.RegularExpressions.RegexOptions.IgnoreCase));
        foreach (var forbidden in new[] { "ActorId", "Cursor =", "PanelItemPresentation", "activity_log" })
        {
            Assert.IsFalse(name.Contains(forbidden, StringComparison.OrdinalIgnoreCase), name);
        }
    }
}
