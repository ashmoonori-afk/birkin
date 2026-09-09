using System.IO;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Support;

[TestClass]
public sealed class ProviderOfficeScreenshotTests
{
    [TestMethod]
    public async Task LayoutVisibility_RejectsHiddenOuterParentAndOuterClipping()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            var root = new Canvas { Width = 200, Height = 200 };
            var outer = new Canvas { Width = 100, Height = 20, ClipToBounds = true };
            var viewport = new Canvas { Width = 100, Height = 100 };
            var element = new Border { Width = 20, Height = 20 };
            Canvas.SetTop(element, 30);
            viewport.Children.Add(element);
            outer.Children.Add(viewport);
            root.Children.Add(outer);
            var window = new Window { Content = root, Width = 200, Height = 200 };
            try
            {
                window.Show();
                window.UpdateLayout();
                Assert.IsFalse(ProviderOfficeJourneyFlow.IsFullyVisible(element, viewport));
                outer.ClipToBounds = false;
                outer.Visibility = Visibility.Collapsed;
                window.UpdateLayout();
                Assert.IsFalse(ProviderOfficeJourneyFlow.IsFullyVisible(element, viewport));
                await Task.CompletedTask;
            }
            finally
            {
                window.Close();
            }
        });
    }

    [TestMethod]
    public async Task CaptureRedacted_PreservesTheLiveWindowLayout()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            var conversation = new ItemsControl();
            AutomationProperties.SetAutomationId(conversation, "conversation.items");
            var root = new Grid();
            root.Children.Add(conversation);
            var window = new Window
            {
                Content = root,
                Width = 800,
                Height = 600,
                WindowStartupLocation = WindowStartupLocation.Manual,
                Left = 24,
                Top = 24,
            };
            var path = Path.Combine(Path.GetTempPath(), $"birkin-screenshot-{Guid.NewGuid():N}.png");
            try
            {
                window.Show();
                window.UpdateLayout();
                var expected = root.RenderSize;

                ProviderOfficeScreenshot.CaptureRedacted(window, path, 1500, 940);

                Assert.AreEqual(expected, root.RenderSize,
                    "capturing evidence changed the live window layout used by later viewport assertions");
                await Task.CompletedTask;
            }
            finally
            {
                window.Close();
                File.Delete(path);
            }
        });
    }

    [TestMethod]
    public async Task CaptureRedacted_RunsPrepareAfterEvidenceResize()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            var conversation = new ItemsControl();
            AutomationProperties.SetAutomationId(conversation, "conversation.items");
            var root = new Grid();
            root.Children.Add(conversation);
            var window = new Window { Content = root, Width = 800, Height = 600 };
            var path = Path.Combine(Path.GetTempPath(), $"birkin-screenshot-{Guid.NewGuid():N}.png");
            Size preparedSize = default;
            try
            {
                window.Show();
                window.UpdateLayout();

                ProviderOfficeScreenshot.CaptureRedacted(
                    window, path, 1500, 940, prepare: () => preparedSize = root.RenderSize);

                Assert.AreEqual(new Size(1500, 940), preparedSize);
                await Task.CompletedTask;
            }
            finally
            {
                window.Close();
                File.Delete(path);
            }
        });
    }
}
