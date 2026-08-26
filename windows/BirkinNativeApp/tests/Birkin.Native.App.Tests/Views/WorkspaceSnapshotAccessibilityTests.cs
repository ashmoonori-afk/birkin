using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Threading;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
public sealed class WorkspaceSnapshotAccessibilityTests
{
    [TestMethod]
    public async Task WorkingMemoryAndApprovalContainers_ExposeSafeDataItemNames()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        // When
        var facts = await sta.InvokeAsync(() => RealizedContainerFacts());

        // Then
        Assert.AreEqual(2, facts.Length);
        Assert.AreEqual("Working memory item", facts[0].Name);
        Assert.AreEqual("Approval policy item", facts[1].Name);
        Assert.IsTrue(facts.All(fact => fact.ControlType == ControlType.DataItem));
    }

    [TestMethod]
    public async Task CurrentVisibleContainers_DoNotExposePresentationMetadata()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        // When
        var facts = await sta.InvokeAsync(() => RealizedContainerFacts());

        // Then
        var names = string.Join("\n", facts.Select(fact => fact.Name));
        Assert.IsFalse(Regex.IsMatch(names, "[0-9a-f]{32}", RegexOptions.IgnoreCase));
        foreach (var forbidden in new[]
        {
            "ActorId", "Cursor =", "WorkingMemoryRowPresentation", "ApprovalPolicyRowPresentation",
            "ReadOnlyCollection", "terminal lease", "user_message", "assistant_message",
        })
        {
            Assert.IsFalse(names.Contains(forbidden, StringComparison.OrdinalIgnoreCase), forbidden);
        }
    }

    private static ContainerFact[] RealizedContainerFacts()
    {
        var model = new ShellPresentationModel(SynchronizationContext.Current!);
        var view = new WorkspaceSnapshotView(model);
        model.PresentSnapshot(Presentation(), () => { });
        var window = new Window { Content = view, Width = 1500, Height = 940 };
        window.Show();
        try
        {
            view.Dispatcher.Invoke(() => { }, DispatcherPriority.Render);
            view.UpdateLayout();
            var root = AutomationElement.FromHandle(new WindowInteropHelper(window).Handle);
            return new[]
            {
                Fact(root, "Working memory item"),
                Fact(root, "Approval policy item"),
            };
        }
        finally
        {
            window.Close();
        }
    }

    private static ContainerFact Fact(AutomationElement root, string name)
    {
        var element = root.FindFirst(TreeScope.Descendants,
            new PropertyCondition(AutomationElement.NameProperty, name));
        Assert.IsNotNull(element, $"current item container must expose {name}");
        return new ContainerFact(element.Current.Name, element.Current.ControlType);
    }

    private static WorkspaceSnapshotPresentation Presentation() => new(
        1, "session-safe", 7, "instance-safe", "initial", "loopback", 2, "connected", [],
        new ComposerPresentation(false, false, false, false),
        new WorkingMemoryPresentation(1,
            [new WorkingMemoryRowPresentation("Goals", ["Keep values safe"], "None set")]),
        [new ApprovalPolicyRowPresentation("Command execution", "shell", "Ask", "Default", false)],
        [], [], [], new TerminalPresentation(false, 0), MutationAvailabilityPresentation.PhaseOne);

    private static T Find<T>(DependencyObject root, string automationId) where T : DependencyObject
    {
        foreach (var child in Descendants<T>(root))
        {
            if (AutomationProperties.GetAutomationId(child) == automationId) return child;
        }
        throw new AssertFailedException($"Missing automation element: {automationId}");
    }

    private static IEnumerable<T> Descendants<T>(DependencyObject root) where T : DependencyObject
    {
        for (var index = 0; index < VisualTreeHelper.GetChildrenCount(root); index++)
        {
            var child = VisualTreeHelper.GetChild(root, index);
            if (child is T match) yield return match;
            foreach (var descendant in Descendants<T>(child)) yield return descendant;
        }
    }

    private sealed record ContainerFact(string Name, ControlType ControlType);
}
