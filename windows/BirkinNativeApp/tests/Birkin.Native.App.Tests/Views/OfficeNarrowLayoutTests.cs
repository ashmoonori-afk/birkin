using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class OfficeNarrowLayoutTests
{
    [TestMethod]
    public async Task ExpandedForms_AtContextRailWidth_RenderFullWidthAndScrollEveryActionIntoView()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new OfficeView(fixture.Model, fixture.Coordinator);
            var window = new Window { Content = view, Width = 330, Height = 873 };
            try
            {
                window.Show();
                OfficeWorkflowViewHarness.Find<Expander>(view, "office.new-panel").IsExpanded = true;
                OfficeWorkflowViewHarness.Find<Expander>(view, "office.import-panel").IsExpanded = true;
                await view.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ContextIdle);
                window.UpdateLayout();

                var scroll = OfficeWorkflowViewHarness.Find<ScrollViewer>(view, "office.workflow-scroll");
                var controls = new[]
                {
                    "office.request", "office.content", "office.destination", "office.draft",
                    "import.path", "import.browse", "import.submit",
                }.Select(id => OfficeWorkflowViewHarness.Find<FrameworkElement>(view, id)).ToArray();

                Assert.IsTrue(controls.Take(3).All(control => control.ActualWidth >= 280));
                Assert.IsTrue(OfficeWorkflowViewHarness.Find<TextBox>(view, "import.path").ActualWidth >= 280);
                foreach (var control in controls)
                {
                    control.BringIntoView();
                    await view.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ContextIdle);
                    Assert.IsTrue(ProviderOfficeJourneyFlow.IsFullyVisible(control, scroll),
                        $"{control.Name} could not be reached in the narrow Office viewport.");
                }

                var bitmap = new RenderTargetBitmap(
                    (int)view.ActualWidth, (int)view.ActualHeight, 96, 96, PixelFormats.Pbgra32);
                bitmap.Render(view);
                Assert.AreEqual((int)view.ActualWidth, bitmap.PixelWidth);
                Assert.AreEqual((int)view.ActualHeight, bitmap.PixelHeight);
            }
            finally
            {
                window.Close();
            }
        });
    }
}
