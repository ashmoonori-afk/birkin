using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Threading;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
public sealed class WorkspaceSnapshotViewTests
{
    [TestMethod]
    public async Task Bindings_WhenPythonPresentationIsReady_RenderNamedValues()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        // When
        var rendered = await sta.InvokeAsync(() =>
        {
            var model = new ShellPresentationModel(SynchronizationContext.Current!);
            var view = new WorkspaceSnapshotView(model);
            model.PresentConnection(ConnectionPresentation.Create(ConnectionState.Ready));
            model.PresentSnapshot(
                new WorkspaceSnapshotPresentation(
                    1,
                    "native-app",
                    42,
                    "0123456789abcdef0123456789abcdef",
                    "initial",
                    "loopback",
                    6),
                () => { });
            view.Dispatcher.Invoke(() => { }, DispatcherPriority.DataBind);
            return new RenderedValues(
                Text(view, "ConnectionStatusText"),
                Text(view, "TransportText"),
                Text(view, "SessionIdText"),
                Text(view, "CursorText"),
                Text(view, "ResetReasonText"),
                Text(view, "PanelCountText"),
                AutomationIds(view));
        });

        // Then
        Assert.AreEqual("LOCAL · PRIVATE", rendered.ConnectionStatus);
        Assert.AreEqual("loopback", rendered.Transport);
        Assert.AreEqual("native-app", rendered.SessionId);
        Assert.AreEqual("42", rendered.Cursor);
        Assert.AreEqual("initial", rendered.ResetReason);
        Assert.AreEqual("6", rendered.PanelCount);
        CollectionAssert.AreEquivalent(
            new[] { "ConnectionStatusText", "TransportText", "SessionIdText", "CursorText", "ResetReasonText", "PanelCountText" },
            rendered.AutomationIds);
    }

    [TestMethod]
    public async Task MainWindow_WhenConstructed_UsesDevelopmentPreviewTitleAndAllowsKeyboardFocus()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        // When
        var properties = await sta.InvokeAsync(() =>
        {
            var model = new ShellPresentationModel(SynchronizationContext.Current!);
            var window = new MainWindow(model);
            var result = (window.Title, window.ResizeMode, window.Focusable);
            window.Close();
            return result;
        });

        // Then
        Assert.AreEqual("Birkin for Windows - Development Preview", properties.Title);
        Assert.AreEqual(ResizeMode.CanResize, properties.ResizeMode);
        Assert.IsTrue(properties.Focusable);
    }

    private static string Text(FrameworkElement view, string name) =>
        ((TextBlock)view.FindName(name)).Text;

    private static string[] AutomationIds(FrameworkElement view) =>
        new[] { "ConnectionStatusText", "TransportText", "SessionIdText", "CursorText", "ResetReasonText", "PanelCountText" }
            .Select(name => AutomationProperties.GetAutomationId((DependencyObject)view.FindName(name)))
            .ToArray();

    private sealed record RenderedValues(
        string ConnectionStatus,
        string Transport,
        string SessionId,
        string Cursor,
        string ResetReason,
        string PanelCount,
        string[] AutomationIds);
}
