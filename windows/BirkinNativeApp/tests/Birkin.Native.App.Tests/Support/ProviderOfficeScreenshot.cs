using System.IO;
using System.Security.Cryptography;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;

namespace Birkin.Native.App.Tests.Support;

internal sealed record ProviderOfficeScreenshotResult(string Sha256, int Width, int Height);

internal static class ProviderOfficeScreenshot
{
    public static ProviderOfficeScreenshotResult CaptureRedacted(
        Window window,
        string path,
        int width,
        int height,
        Action? prepare = null,
        Action? validate = null)
    {
        var conversation = OfficeWorkflowViewHarness.Find<ItemsControl>(window, "conversation.items");
        var rendered = (FrameworkElement)window.Content;
        var priorVisibility = conversation.Visibility;
        var priorRenderSize = rendered.RenderSize;
        var priorWidth = window.Width;
        var priorHeight = window.Height;
        conversation.Visibility = Visibility.Hidden;
        try
        {
            window.Width = width;
            window.Height = height;
            rendered.Measure(new Size(width, height));
            rendered.Arrange(new Rect(0, 0, width, height));
            prepare?.Invoke();
            window.UpdateLayout();
            window.Dispatcher.Invoke(() => { }, DispatcherPriority.Render);
            var bitmap = new RenderTargetBitmap(width, height, 96, 96, PixelFormats.Pbgra32);
            bitmap.Render(rendered);
            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(bitmap));
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            using var output = File.Create(path);
            encoder.Save(output);
            validate?.Invoke();
        }
        finally
        {
            conversation.Visibility = priorVisibility;
            window.Width = priorWidth;
            window.Height = priorHeight;
            rendered.Measure(priorRenderSize);
            rendered.Arrange(new Rect(new Point(), priorRenderSize));
            window.UpdateLayout();
        }

        return new ProviderOfficeScreenshotResult(
            Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant(),
            width,
            height);
    }
}
