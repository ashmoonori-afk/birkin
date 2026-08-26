using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
public sealed class ShellInteractionVisualStateTests
{
    [TestMethod]
    public async Task ActionButtons_ExposeDistinctNormalHoverPressedDisabledAndFocusedStates()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(() =>
        {
            var resources = new TerminalView().Resources;
            var button = new Button { Content = "Action", Style = (Style)resources["DisabledActionStyle"], IsEnabled = true };
            var window = new Window { Content = button, Width = 240, Height = 120 };
            window.Show();
            try
            {
                button.ApplyTemplate();
                var chrome = (Border?)button.Template.FindName("ActionChrome", button);
                var focusChrome = (Border?)button.Template.FindName("FocusChrome", button);
                Assert.IsNotNull(chrome);
                Assert.IsNotNull(focusChrome);

                // When
                var normal = State(button, chrome, focusChrome, "Normal");
                var hover = State(button, chrome, focusChrome, "MouseOver");
                var pressed = State(button, chrome, focusChrome, "Pressed");
                button.IsEnabled = false;
                var disabled = State(button, chrome, focusChrome, "Disabled");
                var disabledOpacity = chrome.Opacity;
                button.IsEnabled = true;
                _ = State(button, chrome, focusChrome, "Normal");
                var focused = DeclaredFocusState(chrome, focusChrome, "Focused");
                var unfocused = DeclaredFocusState(chrome, focusChrome, "Unfocused");

                // Then
                Assert.AreEqual("#FF1A1C1D/#FF343638/0", normal);
                Assert.AreEqual("#FF242628/#FFE2A44F/0", hover);
                Assert.AreEqual("#FF30271B/#FFF0B65F/0", pressed);
                Assert.AreEqual("#FF141617/#FF2B2D2F/0", disabled);
                Assert.AreEqual("#FF1A1C1D/#FF343638/2", focused);
                Assert.AreEqual("#FF1A1C1D/#FF343638/0", unfocused);
                Assert.AreEqual(1d, button.Opacity, 0.001);
                Assert.AreEqual(0.58, disabledOpacity, 0.001);
                Assert.AreEqual(5, new[] { normal, hover, pressed, disabled, focused }.Distinct().Count());
            }
            finally
            {
                window.Close();
            }
            return Task.CompletedTask;
        });
    }

    private static string State(Button button, Border chrome, Border focusChrome, string state)
    {
        Assert.IsTrue(VisualStateManager.GoToElementState(focusChrome, state, false), $"missing visual state {state}");
        button.Dispatcher.Invoke(() => { }, DispatcherPriority.Render);
        return Snapshot(chrome, focusChrome);
    }

    private static string Snapshot(Border chrome, Border focusChrome)
    {
        var background = ((SolidColorBrush)chrome.Background).Color;
        var border = ((SolidColorBrush)chrome.BorderBrush).Color;
        return $"{background}/{border}/{focusChrome.BorderThickness.Left:0}";
    }

    private static string DeclaredFocusState(Border chrome, Border focusChrome, string stateName)
    {
        var states = VisualStateManager.GetVisualStateGroups(focusChrome).Cast<VisualStateGroup>()
            .SelectMany(group => group.States.Cast<VisualState>()).ToArray();
        var state = states.Single(item => item.Name == stateName);
        var normalColors = states.Single(item => item.Name == "Normal").Storyboard.Children
            .OfType<ColorAnimation>().Select(animation => animation.To).ToArray();
        var thickness = state.Storyboard.Children.OfType<ThicknessAnimation>().Single().To;
        return $"{normalColors[0]}/{normalColors[1]}/{thickness?.Left:0}";
    }
}
