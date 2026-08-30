using System.Diagnostics;
using System.IO;
using System.Windows.Automation;
using Birkin.Native.App.Startup;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Startup;

[TestClass]
public sealed class FirstRunWindowTests
{
    [TestMethod]
    [TestCategory("WindowsOnly")]
    public void Startup_WhenPathCannotResolveBirkin_ShowsGuidanceAndRetries()
    {
        var executable = Path.ChangeExtension(
            typeof(App).Assembly.Location,
            ".exe");
        Assert.IsTrue(
            File.Exists(executable),
            $"The WPF application executable was not found at {executable}.");

        var startInfo = new ProcessStartInfo(executable)
        {
            UseShellExecute = false,
        };
        startInfo.Environment["PATH"] = Path.Combine(
            Path.GetTempPath(),
            $"birkin-empty-{Guid.NewGuid():N}");
        startInfo.Environment[ExecutablePathSettings.EnvironmentVariableName] =
            "birkin";

        using var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException(
                "The WPF application process could not be started.");
        try
        {
            Assert.IsTrue(
                process.WaitForInputIdle(milliseconds: 10_000),
                "The WPF dispatcher did not become ready.");
            process.Refresh();
            Assert.AreNotEqual(
                IntPtr.Zero,
                process.MainWindowHandle,
                "Bridge launch failure prevented the main window from being shown.");
            Assert.AreEqual(
                "Birkin for Windows - Development Preview",
                process.MainWindowTitle);

            var window = AutomationElement.FromHandle(
                process.MainWindowHandle);
            var title = FindByAutomationId(
                window,
                "startup.failure.title");
            Assert.AreEqual(
                "birkin 실행 파일을 찾을 수 없습니다",
                title.Current.Name);

            var retry = FindByAutomationId(
                window,
                "startup.failure.retry");
            Assert.IsTrue(retry.Current.IsEnabled);
            using var disabled = new ManualResetEventSlim();
            using var enabledAgain = new ManualResetEventSlim();
            var sawDisabled = 0;
            AutomationPropertyChangedEventHandler handler = (_, change) =>
            {
                if (change.Property != AutomationElement.IsEnabledProperty
                    || change.NewValue is not bool isEnabled)
                {
                    return;
                }
                if (!isEnabled)
                {
                    _ = Interlocked.Exchange(ref sawDisabled, 1);
                    disabled.Set();
                }
                else if (Volatile.Read(ref sawDisabled) == 1)
                {
                    enabledAgain.Set();
                }
            };
            Automation.AddAutomationPropertyChangedEventHandler(
                retry,
                TreeScope.Element,
                handler,
                AutomationElement.IsEnabledProperty);
            try
            {
                var invoke = (InvokePattern)retry.GetCurrentPattern(
                    InvokePattern.Pattern);
                invoke.Invoke();
                Assert.IsTrue(
                    disabled.Wait(TimeSpan.FromSeconds(10)),
                    "Retry did not enter its in-progress state.");
                Assert.IsTrue(
                    enabledAgain.Wait(TimeSpan.FromSeconds(10)),
                    "Retry did not return to the recoverable failure state.");
            }
            finally
            {
                Automation.RemoveAutomationPropertyChangedEventHandler(
                    retry,
                    handler);
            }

            Assert.AreEqual(
                "birkin 실행 파일을 찾을 수 없습니다",
                FindByAutomationId(
                    window,
                    "startup.failure.title").Current.Name);
        }
        finally
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
                Assert.IsTrue(
                    process.WaitForExit(milliseconds: 5_000),
                    "The WPF application did not exit after test cleanup.");
            }
        }
    }

    private static AutomationElement FindByAutomationId(
        AutomationElement root,
        string automationId) =>
        root.FindFirst(
            TreeScope.Descendants,
            new PropertyCondition(
                AutomationElement.AutomationIdProperty,
                automationId))
        ?? throw new AssertFailedException(
            $"Missing automation element: {automationId}");
}
