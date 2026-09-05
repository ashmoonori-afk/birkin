namespace Birkin.Native.Shell.Presentation;

public sealed record ResolvedColumns(
    double NavigationWidth,
    double PrimaryWidth,
    double ContextWidth,
    int SplitterCount);

public static class LayoutArbiter
{
    public static ResolvedColumns Resolve(LayoutState state, double availableWidth)
    {
        var navigation = state.Navigation.Visible
            ? Math.Clamp(state.Navigation.Width, LayoutState.NavigationMinWidth, LayoutState.NavigationMaxWidth)
            : 0;
        var context = state.Context.Visible
            ? Math.Clamp(state.Context.Width, LayoutState.ContextMinWidth, LayoutState.ContextMaxWidth)
            : 0;
        var splitters = (state.Navigation.Visible ? 1 : 0) + (state.Context.Visible ? 1 : 0);
        var sideBudget = availableWidth - 24 - (6 * splitters) - 400;
        var overflow = Math.Max(0, navigation + context - sideBudget);

        if (state.LastTouched == LayoutPanel.Navigation)
        {
            Shrink(ref navigation, state.Navigation.Visible ? LayoutState.NavigationMinWidth : 0, ref overflow);
            Shrink(ref context, state.Context.Visible ? LayoutState.ContextMinWidth : 0, ref overflow);
        }
        else
        {
            Shrink(ref context, state.Context.Visible ? LayoutState.ContextMinWidth : 0, ref overflow);
            Shrink(ref navigation, state.Navigation.Visible ? LayoutState.NavigationMinWidth : 0, ref overflow);
        }

        var primary = Math.Max(0, availableWidth - 24 - (6 * splitters) - navigation - context);
        return new ResolvedColumns(navigation, primary, context, splitters);
    }

    private static void Shrink(ref double width, double minimum, ref double overflow)
    {
        var amount = Math.Min(Math.Max(0, width - minimum), overflow);
        width -= amount;
        overflow -= amount;
    }
}
