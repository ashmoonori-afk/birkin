using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
public sealed class LayoutStateViewTests
{
    [TestMethod]
    public async Task ContextToggle_HidesAndRestoresColumnSplitterViewAndChip()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(() =>
        {
            var view = CreateView();
            view.ToggleContextPanel();
            view.CompleteLayoutAnimationsForTesting();
            Assert.AreEqual(0, view.ContextColumn.Width.Value);
            Assert.AreEqual(Visibility.Collapsed, view.ContextSplitter.Visibility);
            Assert.AreEqual(Visibility.Collapsed, view.ContextColumnView.Visibility);
            Assert.AreEqual(Visibility.Visible, view.RestoreContextButton.Visibility);

            view.ToggleContextPanel();
            view.CompleteLayoutAnimationsForTesting();
            Assert.AreEqual(340, view.ContextColumn.Width.Value);
            Assert.AreEqual(Visibility.Visible, view.ContextSplitter.Visibility);
            Assert.AreEqual(Visibility.Visible, view.ContextColumnView.Visibility);
            Assert.AreEqual(Visibility.Collapsed, view.RestoreContextButton.Visibility);
            return true;
        });
    }

    [TestMethod]
    public async Task KeyboardSplitterResize_PersistsUpdatedNavigationWidthAfterInputCompletes()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            var view = CreateView();
            var host = new Window
            {
                Content = view,
                Width = 1500,
                Height = 900,
                ShowInTaskbar = false,
                WindowStyle = WindowStyle.None,
            };
            host.Show();
            host.UpdateLayout();
            try
            {
                var persisted = new TaskCompletionSource<LayoutState>(TaskCreationOptions.RunContinuationsAsynchronously);
                var initial = LayoutState.Default with { Hints = new LayoutHintsState(true) };
                view.AttachLayout(initial, (state, immediate) =>
                {
                    if (!immediate && state.Navigation.Width > initial.Navigation.Width)
                        persisted.TrySetResult(state);
                });
                var source = PresentationSource.FromVisual(view.NavigationSplitter)!;

                for (var index = 0; index < 15; index++)
                {
                    view.NavigationSplitter.RaiseEvent(new KeyEventArgs(
                        Keyboard.PrimaryDevice, source, 0, Key.Right)
                    { RoutedEvent = Keyboard.KeyDownEvent });
                    view.UpdateLayout();
                    view.NavigationSplitter.RaiseEvent(new KeyEventArgs(
                        Keyboard.PrimaryDevice, source, 0, Key.Right)
                    { RoutedEvent = Keyboard.KeyUpEvent });
                }

                var saved = await persisted.Task.WaitAsync(deadline.Token);
                Assert.IsTrue(saved.Navigation.Width > initial.Navigation.Width);
                Assert.AreEqual(saved.Navigation.Width, view.LayoutState.Navigation.Width, 0.01);
            }
            finally
            {
                host.Close();
            }
        });
    }

    [TestMethod]
    public async Task FocusMode_ManualHideBothRestoresPanelsAndNormalRoundTripRestoresVisibility()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(() =>
        {
            var view = CreateView();
            view.AttachLayout(LayoutState.Default with { Hints = new LayoutHintsState(true) }, (_, _) => { });

            view.ToggleNavigationPanel();
            view.ToggleContextPanel();
            view.CompleteLayoutAnimationsForTesting();
            Assert.IsFalse(view.FocusMenuItem.IsChecked, "Manual hiding is not an active focus session.");

            view.FocusMenuItem.RaiseEvent(new RoutedEventArgs(MenuItem.ClickEvent));
            view.CompleteLayoutAnimationsForTesting();
            Assert.IsTrue(view.LayoutState.Navigation.Visible);
            Assert.IsTrue(view.LayoutState.Context.Visible);
            Assert.IsNull(view.LayoutState.FocusRestore);

            view.ToggleContextPanel();
            view.FocusMenuItem.RaiseEvent(new RoutedEventArgs(MenuItem.ClickEvent));
            view.CompleteLayoutAnimationsForTesting();
            Assert.IsTrue(view.FocusMenuItem.IsChecked);
            Assert.IsFalse(view.LayoutState.Navigation.Visible);
            Assert.IsFalse(view.LayoutState.Context.Visible);

            view.FocusMenuItem.RaiseEvent(new RoutedEventArgs(MenuItem.ClickEvent));
            view.CompleteLayoutAnimationsForTesting();
            Assert.IsTrue(view.LayoutState.Navigation.Visible);
            Assert.IsFalse(view.LayoutState.Context.Visible);
            Assert.IsFalse(view.FocusMenuItem.IsChecked);
            return true;
        });
    }

    [TestMethod]
    public async Task PointerSplitterDrag_PersistsWidthAndRestoresPriorKeyboardFocus()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(() =>
        {
            var view = CreateView();
            LayoutState? persisted = null;
            view.AttachLayout(LayoutState.Default with { Hints = new LayoutHintsState(true) },
                (state, immediate) => { if (!immediate) persisted = state; });
            var host = new Window { Content = view, Width = 1500, Height = 900, ShowInTaskbar = false };
            host.Show();
            host.Activate();
            host.UpdateLayout();
            try
            {
                var draft = OfficeWorkflowViewHarness.Find<TextBox>(view, "conversation.draft");
                draft.IsEnabled = true;
                Assert.IsTrue(draft.Focus());
                Assert.AreSame(draft, Keyboard.FocusedElement);

                view.NavigationSplitter.RaiseEvent(new MouseButtonEventArgs(
                    Mouse.PrimaryDevice, 0, MouseButton.Left)
                { RoutedEvent = UIElement.PreviewMouseLeftButtonDownEvent });
                Assert.AreSame(view.NavigationSplitter, Keyboard.Focus(view.NavigationSplitter));
                view.NavigationSplitter.RaiseEvent(new DragStartedEventArgs(0, 0)
                    { RoutedEvent = Thumb.DragStartedEvent });
                view.NavigationColumn.Width = new GridLength(360);
                host.UpdateLayout();
                view.NavigationSplitter.RaiseEvent(new DragCompletedEventArgs(80, 0, false)
                    { RoutedEvent = Thumb.DragCompletedEvent });

                Assert.IsNotNull(persisted);
                Assert.AreEqual(view.NavigationColumn.ActualWidth, persisted.Navigation.Width, 0.01);
                Assert.IsFalse(view.NavigationSplitter.IsKeyboardFocused);
                Assert.AreSame(draft, Keyboard.FocusedElement);
            }
            finally
            {
                host.Close();
            }
            return true;
        });
    }

    [TestMethod]
    public async Task StatusRestoreActions_AreRightAlignedAndTrackHiddenPanels()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(() =>
        {
            var view = CreateView();
            var diagnosticGroup = (FrameworkElement)view.FindName("DiagnosticStatusGroup");
            var restoreGroup = (FrameworkElement)view.FindName("RestoreActionGroup");

            Assert.IsInstanceOfType<Grid>(restoreGroup.Parent);
            Assert.AreEqual(HorizontalAlignment.Center, diagnosticGroup.HorizontalAlignment);
            Assert.AreEqual(HorizontalAlignment.Right, restoreGroup.HorizontalAlignment);
            Assert.AreEqual(Visibility.Collapsed, view.RestoreNavigationButton.Visibility);
            Assert.AreEqual(Visibility.Collapsed, view.RestoreContextButton.Visibility);

            view.ToggleNavigationPanel();
            view.ToggleContextPanel();
            view.CompleteLayoutAnimationsForTesting();
            Assert.AreEqual(Visibility.Visible, restoreGroup.Visibility);
            Assert.AreEqual(Visibility.Visible, view.RestoreNavigationButton.Visibility);
            Assert.AreEqual(Visibility.Visible, view.RestoreContextButton.Visibility);
            return true;
        });
    }

    [TestMethod]
    public async Task SplitterHover_UsesAtLeast150MillisecondDelayedStoryboard()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(() =>
        {
            var view = CreateView();
            var style = (Style)view.FindResource("PanelSplitterStyle");
            var template = (ControlTemplate)style.Setters.OfType<Setter>()
                .Single(setter => setter.Property == Control.TemplateProperty).Value;
            var mouseEnter = template.Triggers.OfType<EventTrigger>()
                .Single(trigger => trigger.RoutedEvent == Mouse.MouseEnterEvent);
            var beginHover = mouseEnter.Actions.OfType<BeginStoryboard>().Single();
            var mouseLeave = template.Triggers.OfType<EventTrigger>()
                .Single(trigger => trigger.RoutedEvent == Mouse.MouseLeaveEvent);
            var removeHover = mouseLeave.Actions.OfType<RemoveStoryboard>().Single();
            var keyboardFocus = template.Triggers.OfType<Trigger>()
                .Single(trigger => trigger.Property == UIElement.IsKeyboardFocusedProperty);

            Assert.IsTrue(beginHover.Storyboard.BeginTime >= TimeSpan.FromMilliseconds(150));
            Assert.AreEqual(beginHover.Name, removeHover.BeginStoryboardName);
            Assert.IsTrue(keyboardFocus.Setters.OfType<Setter>()
                .Any(setter => setter.Property == FrameworkElement.WidthProperty
                    && Equals(setter.Value, 2d)));
            return true;
        });
    }

    [TestMethod]
    public async Task ResetLayout_RestoresDefaultWidthsAndVisibility()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(() =>
        {
            var view = CreateView();
            view.NavigationColumn.Width = new GridLength(400);
            view.ContextColumn.Width = new GridLength(500);
            view.ToggleNavigationPanel();
            view.ToggleContextPanel();
            view.CompleteLayoutAnimationsForTesting();

            view.ResetLayout();
            view.CompleteLayoutAnimationsForTesting();
            Assert.AreEqual(280, view.NavigationColumn.Width.Value);
            Assert.AreEqual(340, view.ContextColumn.Width.Value);
            Assert.AreEqual(Visibility.Visible, view.NavigationColumnView.Visibility);
            Assert.AreEqual(Visibility.Visible, view.ContextColumnView.Visibility);
            return true;
        });
    }

    private static WorkspaceSnapshotView CreateView()
    {
        var view = new WorkspaceSnapshotView(new ShellPresentationModel(SynchronizationContext.Current!));
        view.Measure(new Size(1500, 900));
        view.Arrange(new Rect(0, 0, 1500, 900));
        view.UpdateLayout();
        view.Dispatcher.Invoke(() => { }, DispatcherPriority.Loaded);
        return view;
    }
}
