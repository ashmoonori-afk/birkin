using System.Diagnostics;
using System.IO;
using System.Windows.Automation;
using Birkin.Native.App.Startup;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Startup;

[TestClass]
public sealed class FirstRunWindowTests
{
    private static readonly TimeSpan SurfaceTimeout = TimeSpan.FromSeconds(20);

    [TestMethod]
    [TestCategory("WindowsOnly")]
    public void Startup_WhenPathCannotResolveBirkin_ShowsGuidanceAndRetries()
    {
        var startInfo = FirstRunStartInfo();

        using var process = Process.Start(startInfo) ?? throw new InvalidOperationException("The WPF application process could not be started.");
        try
        {
            var window = WaitForWindow(process);
            process.Refresh();
            Assert.AreNotEqual(
                IntPtr.Zero,
                process.MainWindowHandle,
                "Bridge launch failure prevented the main window from being shown.");
            Assert.AreEqual(
                "Birkin for Windows - Development Preview",
                process.MainWindowTitle);

            var title = WaitForAutomationId(
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
            KillProcessTree(process);
        }
    }

    [TestMethod]
    [TestCategory("WindowsOnly")]
    public void Startup_WhenBridgeAnnouncementArgumentIsInvalid_RecoversInWindow()
    {
        var startInfo = FirstRunStartInfo();
        startInfo.ArgumentList.Add("--bridge-announcement-file");
        startInfo.ArgumentList.Add(Path.Combine(
            Path.GetTempPath(),
            $"birkin-absent-announcement-{Guid.NewGuid():N}.json"));

        using var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("The WPF application process could not be started.");
        try
        {
            var window = WaitForWindow(process);
            process.Refresh();
            Assert.AreNotEqual(
                IntPtr.Zero,
                process.MainWindowHandle,
                "An invalid argument prevented the main window from being shown.");

            var code = WaitForAutomationId(
                window,
                "startup.failure.code");
            Assert.AreEqual(
                "E_CLI_STARTUP",
                code.Current.Name);
            Assert.IsFalse(
                FindByAutomationId(
                    window,
                    "startup.failure.retry").Current.IsEnabled,
                "An invalid argument is not recoverable by retrying startup.");
            process.Refresh();
            Assert.IsFalse(
                process.HasExited,
                "An invalid argument terminated the application instead of presenting "
                + "the in-window recovery surface.");
        }
        finally
        {
            KillProcessTree(process);
        }
    }

    private static ProcessStartInfo FirstRunStartInfo()
    {
        var executable = Path.ChangeExtension(typeof(App).Assembly.Location, ".exe");
        Assert.IsTrue(File.Exists(executable), $"The WPF application executable was not found at {executable}.");

        var startInfo = new ProcessStartInfo(executable)
        {
            UseShellExecute = false,
        };
        startInfo.Environment["PATH"] = Path.Combine(Path.GetTempPath(), $"birkin-empty-{Guid.NewGuid():N}");
        startInfo.Environment[ExecutablePathSettings.EnvironmentVariableName] = "birkin";
        return startInfo;
    }

    private static void KillProcessTree(Process process)
    {
        if (process.HasExited)
        {
            return;
        }
        process.Kill(entireProcessTree: true);
        Assert.IsTrue(
            process.WaitForExit(milliseconds: 5_000),
            "The WPF application did not exit after test cleanup.");
    }

    private static AutomationElement WaitForWindow(Process process)
    {
        var condition = new AndCondition(
            new PropertyCondition(
                AutomationElement.ProcessIdProperty,
                process.Id),
            new PropertyCondition(
                AutomationElement.ClassNameProperty,
                "Window"));
        using var opened = new ManualResetEventSlim();
        AutomationEventHandler handler = (sender, _) =>
        {
            if (sender is AutomationElement openedWindow
                && openedWindow.Current.ProcessId == process.Id
                && openedWindow.Current.ClassName == "Window")
            {
                opened.Set();
            }
        };
        Automation.AddAutomationEventHandler(
            WindowPattern.WindowOpenedEvent,
            AutomationElement.RootElement,
            TreeScope.Children,
            handler);
        try
        {
            return WaitForElement(
                () => AutomationElement.RootElement.FindFirst(
                    TreeScope.Children,
                    condition),
                opened,
                "The application did not open a window.");
        }
        finally
        {
            Automation.RemoveAutomationEventHandler(WindowPattern.WindowOpenedEvent, AutomationElement.RootElement, handler);
        }
    }

    private static AutomationElement WaitForAutomationId(
        AutomationElement window,
        string automationId)
    {
        using var changed = new ManualResetEventSlim();
        Func<AutomationElement?> find = () => window.FindFirst(
            TreeScope.Descendants,
            new PropertyCondition(
                AutomationElement.AutomationIdProperty,
                automationId));
        StructureChangedEventHandler handler = (_, _) =>
        {
            if (find() is not null)
            {
                changed.Set();
            }
        };
        Automation.AddStructureChangedEventHandler(
            window, TreeScope.Subtree, handler);
        try
        {
            return WaitForElement(
                find,
                changed,
                $"Missing automation element: {automationId}");
        }
        finally
        {
            Automation.RemoveStructureChangedEventHandler(window, handler);
        }
    }

    private static AutomationElement WaitForElement(
        Func<AutomationElement?> find,
        ManualResetEventSlim signal,
        string absenceMessage)
    {
        if (find() is { } existingElement)
        {
            return existingElement;
        }
        if (!signal.Wait(SurfaceTimeout))
        {
            throw new AssertFailedException(absenceMessage);
        }
        return find() ?? throw new AssertFailedException(absenceMessage);
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
