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
}
