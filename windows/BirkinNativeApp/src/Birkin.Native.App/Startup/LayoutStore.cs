using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Threading;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Startup;

public sealed class LayoutStore : IDisposable
{
    public const string EnvironmentVariableName = "BIRKIN_LAYOUT_PATH";
    public const int MaximumFileBytes = 64 * 1024;
    private readonly string _path;
    private readonly DispatcherTimer _layoutTimer;
    private readonly DispatcherTimer _windowTimer;
    private LayoutState _pending = LayoutState.Default;
    private bool _loggedWriteFailure;

    public LayoutStore(Dispatcher dispatcher)
        : this(dispatcher, DefaultPath())
    {
    }

    internal LayoutStore(Dispatcher dispatcher, string defaultPath)
    {
        _path = ResolvePath(defaultPath);
        _layoutTimer = CreateTimer(dispatcher, TimeSpan.FromMilliseconds(500));
        _windowTimer = CreateTimer(dispatcher, TimeSpan.FromMilliseconds(1000));
    }

    public string Path => _path;

    public LayoutState Load()
    {
        if (!File.Exists(_path)) return LayoutState.Default;
        try
        {
            using var stream = new FileStream(
                _path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            if (stream.Length > MaximumFileBytes) return RejectOversizedFile();

            var bytes = new byte[MaximumFileBytes + 1];
            var count = 0;
            int read;
            while (count < bytes.Length
                && (read = stream.Read(bytes, count, bytes.Length - count)) > 0)
            {
                count += read;
            }
            if (count > MaximumFileBytes) return RejectOversizedFile();

            var json = Encoding.UTF8.GetString(bytes, 0, count);
            if (LayoutFile.TryParse(json, out var state, out var parseError)) return state;

            RenameBadFile();
            Trace.TraceWarning($"Invalid Birkin layout file: {parseError!.Message}");
            return LayoutState.Default;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            Trace.TraceWarning($"Unable to read Birkin layout: {error.Message}");
            return LayoutState.Default;
        }
    }

    public void Seed(LayoutState state) => _pending = state;

    public void Save(LayoutState state, bool immediate = false, bool windowOnly = false)
    {
        _pending = state;
        if (immediate) { Flush(); return; }
        var timer = windowOnly ? _windowTimer : _layoutTimer;
        timer.Stop();
        timer.Start();
    }

    public void Flush()
    {
        _layoutTimer.Stop();
        _windowTimer.Stop();
        try
        {
            var directory = System.IO.Path.GetDirectoryName(_path)!;
            Directory.CreateDirectory(directory);
            var temporary = _path + ".tmp";
            File.WriteAllText(temporary, LayoutFile.Serialize(_pending), new UTF8Encoding(false));
            File.Move(temporary, _path, true);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            if (!_loggedWriteFailure)
            {
                _loggedWriteFailure = true;
                Trace.TraceError($"Unable to save Birkin layout: {error.Message}");
            }
        }
    }

    public void Dispose()
    {
        Flush();
        _layoutTimer.Tick -= TimerTick;
        _windowTimer.Tick -= TimerTick;
    }

    private DispatcherTimer CreateTimer(Dispatcher dispatcher, TimeSpan interval)
    {
        var timer = new DispatcherTimer(DispatcherPriority.Background, dispatcher) { Interval = interval };
        timer.Tick += TimerTick;
        return timer;
    }

    private void TimerTick(object? sender, EventArgs eventArgs) => Flush();

    private static LayoutState RejectOversizedFile()
    {
        Trace.TraceWarning($"Birkin layout file exceeds {MaximumFileBytes} bytes; defaults will be used.");
        return LayoutState.Default;
    }

    private void RenameBadFile()
    {
        try { File.Move(_path, _path + ".bad", true); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            Trace.TraceWarning($"Unable to quarantine Birkin layout: {error.Message}");
        }
    }

    private static string ResolvePath(string defaultPath)
    {
        var overridden = Environment.GetEnvironmentVariable(EnvironmentVariableName);
        return !string.IsNullOrWhiteSpace(overridden)
            && System.IO.Path.IsPathFullyQualified(overridden)
                ? overridden
                : defaultPath;
    }

    private static string DefaultPath() => System.IO.Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "Birkin",
        "layout.json");
}
