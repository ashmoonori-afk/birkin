using System.IO;
using System.Text;
using System.Windows;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
[DoNotParallelize]
public sealed class MainWindowLayoutIsolationTests : MainWindowTestBase
{
    [TestMethod]
    public async Task ProductionMainWindow_AfterUserLayoutWasHidden_StartsFromCleanIsolatedDefaults()
    {
        var fakeUserDirectory = System.IO.Path.Combine(
            System.IO.Path.GetTempPath(),
            "birkin-fake-user-layout-" + Guid.NewGuid().ToString("N"));
        var fakeUserPath = System.IO.Path.Combine(fakeUserDirectory, "layout.json");
        Directory.CreateDirectory(fakeUserDirectory);
        File.WriteAllText(
            fakeUserPath,
            LayoutFile.Serialize(LayoutState.Default with
            {
                Context = LayoutState.Default.Context with { Visible = false },
            }),
            new UTF8Encoding(false));

        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        try
        {
            await sta.InvokeAsync(() =>
            {
                Environment.SetEnvironmentVariable("BIRKIN_LAYOUT_PATH", fakeUserPath);
                var userStateWindow = CreateWindow();
                try
                {
                    Assert.IsFalse(
                        OfficeWorkflowViewHarness.Snapshot(userStateWindow).LayoutState.Context.Visible,
                        "The production window must demonstrate that an unisolated persisted layout affects it.");
                }
                finally
                {
                    userStateWindow.Close();
                }

                LayoutTestEnvironment.Reset();
                var isolatedWindow = CreateWindow();
                try
                {
                    Assert.AreEqual(
                        LayoutTestEnvironment.LayoutPath,
                        Environment.GetEnvironmentVariable("BIRKIN_LAYOUT_PATH"));
                    Assert.IsTrue(
                        OfficeWorkflowViewHarness.Snapshot(isolatedWindow).LayoutState.Context.Visible,
                        "A later MainWindow test must not inherit the prior hidden context panel.");
                }
                finally
                {
                    isolatedWindow.Close();
                }
                return true;
            });
        }
        finally
        {
            LayoutTestEnvironment.Reset();
            if (Directory.Exists(fakeUserDirectory)) Directory.Delete(fakeUserDirectory, true);
        }
    }

    private static MainWindow CreateWindow()
    {
        var window = new MainWindow(new ShellPresentationModel(SynchronizationContext.Current!))
        {
            ShowInTaskbar = false,
            WindowStyle = WindowStyle.None,
        };
        window.Show();
        window.UpdateLayout();
        return window;
    }
}
