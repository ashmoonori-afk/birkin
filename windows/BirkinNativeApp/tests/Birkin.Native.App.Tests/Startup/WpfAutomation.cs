using System.Diagnostics;
using System.Windows.Automation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Startup;

internal static class WpfAutomation
{
    private static readonly TimeSpan SurfaceTimeout = TimeSpan.FromSeconds(20);

    internal static void KillProcessTree(Process process)
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

    internal static AutomationElement WaitForWindow(Process process)
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
            Automation.RemoveAutomationEventHandler(
                WindowPattern.WindowOpenedEvent,
                AutomationElement.RootElement,
                handler);
        }
    }

    internal static AutomationElement WaitForAutomationId(
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
            window,
            TreeScope.Subtree,
            handler);
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

    internal static AutomationElement FindByAutomationId(
        AutomationElement root,
        string automationId) =>
        root.FindFirst(
            TreeScope.Descendants,
            new PropertyCondition(
                AutomationElement.AutomationIdProperty,
                automationId))
        ?? throw new AssertFailedException(
            $"Missing automation element: {automationId}");

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
}
