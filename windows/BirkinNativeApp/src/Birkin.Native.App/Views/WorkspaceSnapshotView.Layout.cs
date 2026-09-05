using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class WorkspaceSnapshotView
{
    private enum CompactPane { Navigation, Primary, Context }

    private LayoutState _layout = LayoutState.Default;
    private Action<LayoutState, bool>? _saveLayout;
    private DispatcherTimer? _tipTimer;
    private IInputElement? _splitterRestoreFocus;
    private LayoutFocusRestore? _documentFocusRestore;
    private CompactPane _compactPane = CompactPane.Primary;
    private bool _compactMode;

    public static RoutedCommand ToggleNavigationCommand { get; } = new();
    public static RoutedCommand ToggleContextCommand { get; } = new();
    public static RoutedCommand ToggleFocusCommand { get; } = new();
    public static RoutedCommand ToggleDocumentFocusCommand { get; } = new();
    public static RoutedCommand ResetLayoutCommand { get; } = new();

    public LayoutState LayoutState => _layout;

    private void InitializeLayoutBehavior()
    {
        CommandBindings.Add(new CommandBinding(ToggleNavigationCommand, (_, _) => ToggleNavigationPanel()));
        CommandBindings.Add(new CommandBinding(ToggleContextCommand, (_, _) => ToggleContextPanel()));
        CommandBindings.Add(new CommandBinding(ToggleFocusCommand, (_, _) => ToggleFocusMode()));
        CommandBindings.Add(new CommandBinding(ToggleDocumentFocusCommand, (_, _) => ToggleDocumentFocusMode()));
        CommandBindings.Add(new CommandBinding(ResetLayoutCommand, (_, _) => ResetLayout()));
        PreviewKeyDown += (_, _) => HideLayoutTip();
        NavigationSplitter.KeyUp += SplitterKeyUp;
        ContextSplitter.KeyUp += SplitterKeyUp;
    }

    public void AttachLayout(LayoutState state, Action<LayoutState, bool> saveLayout)
    {
        _layout = state;
        _saveLayout = saveLayout;
        ApplyLayout(false);
        if (!state.Hints.LayoutTipShown)
        {
            LayoutTipText.Visibility = Visibility.Visible;
            _layout = _layout with { Hints = new LayoutHintsState(true) };
            _saveLayout(_layout, true);
            _tipTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(8) };
            _tipTimer.Tick += (_, _) => HideLayoutTip();
            _tipTimer.Start();
        }
    }

    public void ApplyAvailableWidth(double width)
    {
        if (width <= 0) return;
        _compactMode = width < LayoutState.CompactBreakpoint;
        ApplyLayout(false, width);
    }

    public void ToggleNavigationPanel()
    {
        if (_compactMode) ShowCompactPane(CompactPane.Navigation);
        else SetPanelVisibility(LayoutPanel.Navigation, !_layout.Navigation.Visible);
    }

    public void ToggleContextPanel()
    {
        if (_compactMode) ShowCompactPane(CompactPane.Context);
        else SetPanelVisibility(LayoutPanel.Context, !_layout.Context.Visible);
    }

    public void ToggleDocumentFocusMode()
    {
        if (_compactMode)
        {
            ShowCompactPane(CompactPane.Context);
            return;
        }
        if (_documentFocusRestore is null)
        {
            _documentFocusRestore = new LayoutFocusRestore(
                _layout.Navigation.Visible, _layout.Context.Visible);
        }
        else
        {
            _layout = _layout with
            {
                Navigation = _layout.Navigation with { Visible = _documentFocusRestore.Navigation },
                Context = _layout.Context with { Visible = _documentFocusRestore.Context },
            };
            _documentFocusRestore = null;
        }
        ApplyLayout(true);
    }

    public void ShowContextForCurrentWidth()
    {
        if (_compactMode) ShowCompactPane(CompactPane.Context);
    }

    public void ResetLayout()
    {
        var window = _layout.Window;
        var hints = _layout.Hints;
        _documentFocusRestore = null;
        _compactPane = CompactPane.Primary;
        _layout = LayoutState.Default with { Window = window, Hints = hints };
        ApplyLayout(true);
        _saveLayout?.Invoke(_layout, true);
    }

    public void CompleteLayoutAnimationsForTesting() => ApplyLayout(false);

    private void SetPanelVisibility(LayoutPanel panel, bool visible)
    {
        if (panel == LayoutPanel.Navigation)
        {
            _layout = _layout with
            {
                Navigation = _layout.Navigation with { Visible = visible },
                LastTouched = LayoutPanel.Navigation,
                FocusRestore = null,
            };
        }
        else
        {
            _layout = _layout with
            {
                Context = _layout.Context with { Visible = visible },
                LastTouched = LayoutPanel.Context,
                FocusRestore = null,
            };
        }
        ApplyLayout(true);
        _saveLayout?.Invoke(_layout, true);
    }

    private void ApplyLayout(bool animate, double? availableWidth = null)
    {
        if (_compactMode)
        {
            ApplySinglePane(
                _compactPane == CompactPane.Navigation,
                _compactPane == CompactPane.Primary,
                _compactPane == CompactPane.Context);
            NavigationMenuItem.IsChecked = _compactPane == CompactPane.Navigation;
            ContextMenuItem.IsChecked = _compactPane == CompactPane.Context;
            FocusMenuItem.IsChecked = _compactPane == CompactPane.Primary;
            DocumentFocusMenuItem.IsChecked = _compactPane == CompactPane.Context;
            return;
        }
        if (_documentFocusRestore is not null)
        {
            ApplySinglePane(false, false, true);
            NavigationMenuItem.IsChecked = false;
            ContextMenuItem.IsChecked = true;
            FocusMenuItem.IsChecked = false;
            DocumentFocusMenuItem.IsChecked = true;
            return;
        }
        PrimaryColumnDefinition.MinWidth = 400;
        PrimaryColumnDefinition.Width = new GridLength(1, GridUnitType.Star);
        PrimaryColumnView.Visibility = Visibility.Visible;
        NavigationColumn.MaxWidth = LayoutState.NavigationMaxWidth;
        ContextColumn.MaxWidth = LayoutState.ContextMaxWidth;
        DiagnosticStatusGroup.Visibility = Visibility.Visible;
        var resolved = LayoutArbiter.Resolve(
            _layout, availableWidth ?? (ActualWidth > 0 ? ActualWidth : _layout.Window.Width));
        ApplyPanel(NavigationColumn, NavigationColumnView, NavigationSplitterColumn, NavigationSplitter,
            _layout.Navigation.Visible, resolved.NavigationWidth, LayoutState.NavigationMinWidth, animate);
        ApplyPanel(ContextColumn, ContextColumnView, ContextSplitterColumn, ContextSplitter,
            _layout.Context.Visible, resolved.ContextWidth, LayoutState.ContextMinWidth, animate);
        NavigationMenuItem.IsChecked = _layout.Navigation.Visible;
        ContextMenuItem.IsChecked = _layout.Context.Visible;
        FocusMenuItem.IsChecked = _layout.FocusRestore is not null;
        DocumentFocusMenuItem.IsChecked = false;
        RestoreNavigationButton.Visibility = NavigationHotStrip.Visibility =
            _layout.Navigation.Visible ? Visibility.Collapsed : Visibility.Visible;
        RestoreContextButton.Visibility = ContextHotStrip.Visibility =
            _layout.Context.Visible ? Visibility.Collapsed : Visibility.Visible;
        RestoreNavigationButton.IsEnabled = NavigationHotStrip.IsEnabled = !_layout.Navigation.Visible;
        RestoreContextButton.IsEnabled = ContextHotStrip.IsEnabled = !_layout.Context.Visible;
    }

    private void ApplySinglePane(bool navigation, bool primary, bool context)
    {
        NavigationColumn.MinWidth = 0;
        NavigationColumn.MaxWidth = double.PositiveInfinity;
        NavigationColumn.Width = navigation ? new GridLength(1, GridUnitType.Star) : new GridLength(0);
        NavigationColumnView.Visibility = navigation ? Visibility.Visible : Visibility.Collapsed;
        PrimaryColumnDefinition.MinWidth = 0;
        PrimaryColumnDefinition.Width = primary ? new GridLength(1, GridUnitType.Star) : new GridLength(0);
        PrimaryColumnView.Visibility = primary ? Visibility.Visible : Visibility.Collapsed;
        ContextColumn.MinWidth = 0;
        ContextColumn.MaxWidth = double.PositiveInfinity;
        ContextColumn.Width = context ? new GridLength(1, GridUnitType.Star) : new GridLength(0);
        ContextColumnView.Visibility = context ? Visibility.Visible : Visibility.Collapsed;
        NavigationSplitterColumn.Width = ContextSplitterColumn.Width = new GridLength(0);
        NavigationSplitter.Visibility = ContextSplitter.Visibility = Visibility.Collapsed;
        DiagnosticStatusGroup.Visibility = Visibility.Collapsed;
        LayoutTipText.Visibility = Visibility.Collapsed;
        RestoreNavigationButton.Visibility = RestoreContextButton.Visibility = Visibility.Collapsed;
        NavigationHotStrip.Visibility = ContextHotStrip.Visibility = Visibility.Collapsed;
    }

    private void ShowCompactPane(CompactPane pane)
    {
        _compactPane = pane;
        ApplyLayout(false);
    }

    private static void ApplyPanel(
        ColumnDefinition column, FrameworkElement content, ColumnDefinition splitterColumn,
        GridSplitter splitter, bool visible, double width, double minimum, bool animate)
    {
        column.BeginAnimation(ColumnDefinition.WidthProperty, null);
        content.BeginAnimation(OpacityProperty, null);
        var useAnimation = animate && content.IsLoaded && SystemParameters.ClientAreaAnimation;
        if (visible)
        {
            content.Visibility = Visibility.Visible;
            splitter.Visibility = Visibility.Visible;
            splitterColumn.Width = new GridLength(6);
            column.MinWidth = minimum;
            if (useAnimation)
            {
                column.MinWidth = 0;
                column.Width = new GridLength(0);
                column.BeginAnimation(ColumnDefinition.WidthProperty, WidthAnimation(0, width, false));
                content.Opacity = 0;
                var opacity = new DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(100))
                { BeginTime = TimeSpan.FromMilliseconds(60) };
                opacity.Completed += (_, _) =>
                {
                    column.BeginAnimation(ColumnDefinition.WidthProperty, null);
                    column.Width = new GridLength(width);
                    column.MinWidth = minimum;
                };
                content.BeginAnimation(OpacityProperty, opacity);
            }
            else
            {
                column.Width = new GridLength(width);
                content.Opacity = 1;
            }
        }
        else if (useAnimation)
        {
            column.MinWidth = 0;
            var animation = WidthAnimation(column.ActualWidth, 0, true);
            animation.Completed += (_, _) => CollapsePanel(column, content, splitterColumn, splitter);
            column.BeginAnimation(ColumnDefinition.WidthProperty, animation);
            content.BeginAnimation(OpacityProperty, new DoubleAnimation(1, 0, TimeSpan.FromMilliseconds(100)));
        }
        else
        {
            CollapsePanel(column, content, splitterColumn, splitter);
        }
    }

    private static GridLengthAnimation WidthAnimation(double from, double to, bool easeIn) => new()
    {
        From = new GridLength(from),
        To = new GridLength(to),
        Duration = TimeSpan.FromMilliseconds(160),
        EasingFunction = new CubicEase { EasingMode = easeIn ? EasingMode.EaseIn : EasingMode.EaseOut },
    };

    private static void CollapsePanel(
        ColumnDefinition column, FrameworkElement content,
        ColumnDefinition splitterColumn, GridSplitter splitter)
    {
        column.BeginAnimation(ColumnDefinition.WidthProperty, null);
        column.MinWidth = 0;
        column.Width = new GridLength(0);
        splitterColumn.Width = new GridLength(0);
        splitter.Visibility = Visibility.Collapsed;
        content.Visibility = Visibility.Collapsed;
    }

    private void CaptureSplitter(LayoutPanel panel, double width)
    {
        if (panel == LayoutPanel.Navigation)
            _layout = _layout with
            {
                Navigation = new LayoutColumnState(Math.Clamp(width,
                    LayoutState.NavigationMinWidth, LayoutState.NavigationMaxWidth), true),
                LastTouched = panel,
            };
        else
            _layout = _layout with
            {
                Context = new LayoutColumnState(Math.Clamp(width,
                    LayoutState.ContextMinWidth, LayoutState.ContextMaxWidth), true),
                LastTouched = panel,
            };
        ApplyLayout(false);
        _saveLayout?.Invoke(_layout, false);
    }

    private void SplitterKeyUp(object sender, KeyEventArgs eventArgs)
    {
        if (eventArgs.Key is not (Key.Left or Key.Right)) return;
        var panel = ReferenceEquals(sender, NavigationSplitter)
            ? LayoutPanel.Navigation
            : LayoutPanel.Context;
        _ = Dispatcher.BeginInvoke(DispatcherPriority.Loaded, new Action(() =>
            CaptureSplitter(panel, panel == LayoutPanel.Navigation
                ? NavigationColumn.ActualWidth
                : ContextColumn.ActualWidth)));
    }

    private void HideLayoutTip()
    {
        _tipTimer?.Stop();
        LayoutTipText.Visibility = Visibility.Collapsed;
    }

    private void ToggleNavigationClicked(object sender, RoutedEventArgs eventArgs) => ToggleNavigationPanel();
    private void ToggleContextClicked(object sender, RoutedEventArgs eventArgs) => ToggleContextPanel();
    private void ToggleDocumentFocusClicked(object sender, RoutedEventArgs eventArgs) => ToggleDocumentFocusMode();
    private void ResetLayoutClicked(object sender, RoutedEventArgs eventArgs) => ResetLayout();
    private void ShowNavigationClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (!_layout.Navigation.Visible) SetPanelVisibility(LayoutPanel.Navigation, true);
    }
    private void ShowContextClicked(object sender, RoutedEventArgs eventArgs)
    {
        if (!_layout.Context.Visible) SetPanelVisibility(LayoutPanel.Context, true);
    }
    private void SplitterPreviewMouseLeftButtonDown(object sender, MouseButtonEventArgs eventArgs) =>
        _splitterRestoreFocus = ReferenceEquals(Keyboard.FocusedElement, sender)
            ? null
            : Keyboard.FocusedElement;
    private void SplitterDragStarted(object sender, DragStartedEventArgs eventArgs)
    {
        if (!ReferenceEquals(Keyboard.FocusedElement, sender))
            _splitterRestoreFocus = Keyboard.FocusedElement;
    }
    private void NavigationSplitterDragCompleted(object sender, DragCompletedEventArgs eventArgs)
    {
        CaptureSplitter(LayoutPanel.Navigation, NavigationColumn.ActualWidth);
        RestoreFocusAfterSplitterDrag();
    }
    private void ContextSplitterDragCompleted(object sender, DragCompletedEventArgs eventArgs)
    {
        CaptureSplitter(LayoutPanel.Context, ContextColumn.ActualWidth);
        RestoreFocusAfterSplitterDrag();
    }
    private void RestoreFocusAfterSplitterDrag()
    {
        var restored = _splitterRestoreFocus is UIElement { IsVisible: true, IsEnabled: true } prior
            && prior.Focus();
        _splitterRestoreFocus = null;
        if (!restored && !PrimaryColumnView.Focus()) Focus();
    }
    private void NavigationSplitterDoubleClicked(object sender, MouseButtonEventArgs eventArgs)
    {
        CaptureSplitter(LayoutPanel.Navigation, LayoutState.NavigationDefaultWidth);
        eventArgs.Handled = true;
    }
    private void ContextSplitterDoubleClicked(object sender, MouseButtonEventArgs eventArgs)
    {
        CaptureSplitter(LayoutPanel.Context, LayoutState.ContextDefaultWidth);
        eventArgs.Handled = true;
    }
}
