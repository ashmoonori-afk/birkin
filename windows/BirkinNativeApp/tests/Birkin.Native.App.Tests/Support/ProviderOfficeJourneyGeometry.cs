using System.Windows;

namespace Birkin.Native.App.Tests.Support;

internal static class ProviderOfficeJourneyGeometry
{
    public static async Task RenderBarrierAsync(Window window)
    {
        await window.Dispatcher.InvokeAsync(window.UpdateLayout);
        await window.Dispatcher.InvokeAsync(
            () => { },
            System.Windows.Threading.DispatcherPriority.ContextIdle);
        window.UpdateLayout();
    }

    public static bool IsInViewport(FrameworkElement element, FrameworkElement viewport)
    {
        var bounds = element.TransformToAncestor(viewport).TransformBounds(
            new Rect(new Point(0, 0), element.RenderSize));
        var visible = new Rect(new Point(0, 0), viewport.RenderSize);
        return element.IsVisible
            && bounds.Left >= visible.Left - 1
            && bounds.Top >= visible.Top - 1
            && bounds.Right <= visible.Right + 1
            && bounds.Bottom <= visible.Bottom + 1;
    }
}
