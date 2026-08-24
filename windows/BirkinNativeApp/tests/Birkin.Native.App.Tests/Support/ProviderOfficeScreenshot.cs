using System.IO;
using System.Security.Cryptography;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace Birkin.Native.App.Tests.Support;

internal static class ProviderOfficeScreenshot
{
    public static string CaptureRedacted(Window window, string path)
    {
        var conversation = OfficeWorkflowViewHarness.Find<ItemsControl>(window, "conversation.items");
        var priorVisibility = conversation.Visibility;
        conversation.Visibility = Visibility.Hidden;
        try
        {
            window.UpdateLayout();
            var rendered = (FrameworkElement)window.Content;
            var width = Math.Max(1, (int)Math.Ceiling(rendered.ActualWidth));
            var height = Math.Max(1, (int)Math.Ceiling(rendered.ActualHeight));
            var bitmap = new RenderTargetBitmap(width, height, 96, 96, PixelFormats.Pbgra32);
            bitmap.Render(rendered);
            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(bitmap));
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            using var output = File.Create(path);
            encoder.Save(output);
        }
        finally
        {
            conversation.Visibility = priorVisibility;
            window.UpdateLayout();
        }

        return Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
    }
}
