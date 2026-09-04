namespace Birkin.Native.Shell.Presentation;

public enum LayoutPanel
{
    Navigation,
    Context,
}

public enum LayoutWindowMode
{
    Normal,
    Maximized,
}

public sealed record LayoutColumnState(double Width, bool Visible);

public sealed record LayoutFocusRestore(bool Navigation, bool Context);

public sealed record LayoutWindowState(
    double Width,
    double Height,
    double? Left,
    double? Top,
    LayoutWindowMode State);

public sealed record LayoutHintsState(bool LayoutTipShown);

public sealed record LayoutState(
    LayoutColumnState Navigation,
    LayoutColumnState Context,
    LayoutPanel LastTouched,
    LayoutFocusRestore? FocusRestore,
    LayoutWindowState Window,
    LayoutHintsState Hints)
{
    public const double NavigationDefaultWidth = 280;
    public const double NavigationMinWidth = 240;
    public const double NavigationMaxWidth = 480;
    public const double ContextDefaultWidth = 340;
    public const double ContextMinWidth = 300;
    public const double ContextMaxWidth = 600;
    public const double WindowMinWidth = 1100;
    public const double WindowMinHeight = 700;
    public const double WindowMaxWidth = 16384;
    public const double WindowMaxHeight = 16384;

    public static LayoutState Default { get; } = new(
        new LayoutColumnState(NavigationDefaultWidth, true),
        new LayoutColumnState(ContextDefaultWidth, true),
        LayoutPanel.Context,
        null,
        new LayoutWindowState(1500, 940, null, null, LayoutWindowMode.Normal),
        new LayoutHintsState(false));
}
