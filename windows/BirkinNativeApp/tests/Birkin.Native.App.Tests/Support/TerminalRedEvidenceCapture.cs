using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace Birkin.Native.App.Tests.Support;

internal static class TerminalRedEvidenceCapture
{
    private static readonly string[] SensitiveTerms =
        ["bootstrap_secret", "session_capability", "lease", "token"];

    public static string EvidenceDirectory
    {
        get
        {
            var directory = new DirectoryInfo(AppContext.BaseDirectory);
            while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "pyproject.toml")))
            {
                directory = directory.Parent;
            }
            var root = directory?.FullName
                ?? throw new InvalidOperationException("repository root was not found");
            return Path.Combine(root, ".omo", "evidence", "native-windows-conpty", "wave-09-wpf-red");
        }
    }

    public static void CaptureWindow(Window window, int width, int height)
    {
        Directory.CreateDirectory(EvidenceDirectory);
        window.Width = width;
        window.Height = height;
        window.UpdateLayout();
        var bitmap = new RenderTargetBitmap(
            Math.Max(1, (int)Math.Ceiling(window.ActualWidth)),
            Math.Max(1, (int)Math.Ceiling(window.ActualHeight)),
            96,
            96,
            PixelFormats.Pbgra32);
        bitmap.Render(window);
        var encoder = new PngBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(bitmap));
        using var stream = File.Create(Path.Combine(EvidenceDirectory, $"terminal-missing-{width}x{height}.png"));
        encoder.Save(stream);
    }

    public static void CaptureUiaTree(Window window)
    {
        var root = AutomationElement.FromHandle(new WindowInteropHelper(window).Handle);
        var builder = new StringBuilder();
        Append(root, builder, 0);
        var text = builder.ToString();
        AssertRedacted(text);
        File.WriteAllText(Path.Combine(EvidenceDirectory, "uia-tree.redacted.txt"), text, Encoding.UTF8);
    }

    public static void WriteJourneyReceipt(
        int bridgePid,
        bool hiddenBridge,
        bool bridgeExited,
        bool temporaryRootDeleted,
        IReadOnlyList<string> subscribedEvents,
        IReadOnlyList<string> missingControls)
    {
        var receipt = new
        {
            schema = "birkin.native-windows-conpty.wave-09-wpf-red.journey.redacted.v1",
            result = "RED",
            bridge = new { pid = bridgePid, hidden = hiddenBridge, exited = bridgeExited },
            subscriptions_before_actions = subscribedEvents,
            expected_controls_missing = missingControls,
            cleanup = new { temporary_root_deleted = temporaryRootDeleted },
            sensitive_values_persisted = false,
        };
        var json = JsonSerializer.Serialize(receipt, new JsonSerializerOptions { WriteIndented = true });
        AssertRedacted(json);
        File.WriteAllText(Path.Combine(EvidenceDirectory, "live-journey.receipt.redacted.json"), json + Environment.NewLine);
    }

    public static bool HasConsoleWindow(int processId)
    {
        try
        {
            using var process = Process.GetProcessById(processId);
            return process.MainWindowHandle != IntPtr.Zero;
        }
        catch (ArgumentException)
        {
            return false;
        }
    }

    private static void Append(AutomationElement element, StringBuilder builder, int depth)
    {
        var id = element.Current.AutomationId;
        var name = element.Current.Name;
        var type = element.Current.ControlType.ProgrammaticName;
        builder.Append(' ', depth * 2)
            .Append(type).Append(" id=").Append(Redact(id))
            .Append(" name=").Append(Redact(name)).AppendLine();
        var walker = TreeWalker.ControlViewWalker;
        for (var child = walker.GetFirstChild(element); child is not null; child = walker.GetNextSibling(child))
        {
            Append(child, builder, depth + 1);
        }
    }

    private static string Redact(string value) =>
        SensitiveTerms.Any(term => value.Contains(term, StringComparison.OrdinalIgnoreCase))
            ? "[REDACTED]"
            : value.Replace('\r', ' ').Replace('\n', ' ');

    private static void AssertRedacted(string value)
    {
        foreach (var term in SensitiveTerms)
        {
            if (value.Contains(term, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException($"evidence contains forbidden term: {term}");
            }
        }
    }
}
