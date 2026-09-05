using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Threading;
using Birkin.Native.App.Startup;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Startup;

[TestClass]
[DoNotParallelize]
public sealed class LayoutStateStoreTests
{
    [TestMethod]
    public void Save_WithExistingDestinationAndTemporaryFile_ReplacesBothAtomically()
    {
        WithStorePath((store, path) =>
        {
            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(path)!);
            File.WriteAllText(path, "old destination");
            File.WriteAllText(path + ".tmp", "old temporary");
            var state = LayoutState.Default with { Navigation = new LayoutColumnState(360, false) };

            store.Save(state, immediate: true);

            Assert.AreEqual(state, store.Load());
            var bytes = File.ReadAllBytes(path);
            Assert.IsFalse(bytes.AsSpan().StartsWith(Encoding.UTF8.Preamble));
            Assert.IsFalse(File.Exists(path + ".tmp"));
        });
    }

    [TestMethod]
    public void Save_RelativeOverride_UsesInjectedDefaultAndDoesNotWriteRelativeTarget()
    {
        var directory = NewDirectory();
        var relative = "birkin-layout-relative-" + Guid.NewGuid() + ".json";
        var fallback = System.IO.Path.Combine(directory, "default.json");
        var previous = Environment.GetEnvironmentVariable(LayoutStore.EnvironmentVariableName);
        Environment.SetEnvironmentVariable(LayoutStore.EnvironmentVariableName, relative);
        try
        {
            using var store = new LayoutStore(Dispatcher.CurrentDispatcher, fallback);
            store.Save(LayoutState.Default, immediate: true);

            Assert.AreEqual(fallback, store.Path);
            Assert.IsTrue(File.Exists(fallback));
            Assert.IsFalse(File.Exists(relative));
        }
        finally
        {
            Environment.SetEnvironmentVariable(LayoutStore.EnvironmentVariableName, previous);
            if (Directory.Exists(directory)) Directory.Delete(directory, true);
        }
    }

    [TestMethod]
    public void Dispose_WithDeferredSave_FlushesExactPendingState()
    {
        var directory = NewDirectory();
        var path = System.IO.Path.Combine(directory, "layout.json");
        var state = LayoutState.Default with
        {
            Context = new LayoutColumnState(512, false),
            LastTouched = LayoutPanel.Navigation,
        };
        var store = CreateStore(path);

        store.Save(state);
        Assert.IsFalse(File.Exists(path));
        store.Dispose();

        Assert.AreEqual(state, LayoutFile.Parse(File.ReadAllText(path)));
        Directory.Delete(directory, true);
    }

    [TestMethod]
    public void Load_OversizedFile_ReportsOnceWithoutQuarantineAndReturnsDefaults()
    {
        WithStorePath((store, path) =>
        {
            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(path)!);
            File.WriteAllBytes(path, new byte[LayoutStore.MaximumFileBytes + 1]);

            var trace = CaptureTrace(store.Load, out var state);

            Assert.AreEqual(LayoutState.Default, state);
            Assert.AreEqual(1, Count(trace, "Birkin layout file exceeds 65536 bytes"));
            Assert.IsTrue(File.Exists(path));
            Assert.IsFalse(File.Exists(path + ".bad"));
        });
    }

    [TestMethod]
    public void Load_InvalidJson_RenamesBadFileAndReturnsDefaults()
    {
        WithStorePath((store, path) =>
        {
            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(path)!);
            File.WriteAllText(path, "{not json");

            Assert.AreEqual(LayoutState.Default, store.Load());
            Assert.IsFalse(File.Exists(path));
            Assert.IsTrue(File.Exists(path + ".bad"));
        });
    }

    [TestMethod]
    public void Load_ReadFailure_ReportsOnceWithoutThrowing()
    {
        WithStorePath((store, path) =>
        {
            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(path)!);
            File.WriteAllText(path, "{}");
            using var locked = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None);

            var trace = CaptureTrace(store.Load, out var state);

            Assert.AreEqual(LayoutState.Default, state);
            Assert.AreEqual(1, Count(trace, "Unable to read Birkin layout:"));
        });
    }

    [TestMethod]
    public void Save_WriteFailure_ReportsOnceWithoutThrowing()
    {
        var directory = NewDirectory();
        var blockedParent = System.IO.Path.Combine(directory, "not-a-directory");
        Directory.CreateDirectory(directory);
        File.WriteAllText(blockedParent, "blocked");
        var store = CreateStore(System.IO.Path.Combine(blockedParent, "layout.json"));
        try
        {
            var trace = CaptureTrace(() =>
            {
                store.Save(LayoutState.Default, immediate: true);
                store.Flush();
            });

            Assert.AreEqual(1, Count(trace, "Unable to save Birkin layout:"));
        }
        finally
        {
            store.Dispose();
            Directory.Delete(directory, true);
        }
    }

    private static LayoutStore CreateStore(string path)
    {
        var previous = Environment.GetEnvironmentVariable(LayoutStore.EnvironmentVariableName);
        Environment.SetEnvironmentVariable(LayoutStore.EnvironmentVariableName, path);
        try { return new LayoutStore(Dispatcher.CurrentDispatcher); }
        finally { Environment.SetEnvironmentVariable(LayoutStore.EnvironmentVariableName, previous); }
    }

    private static void WithStorePath(Action<LayoutStore, string> action)
    {
        var directory = NewDirectory();
        var path = System.IO.Path.Combine(directory, "layout.json");
        var store = CreateStore(path);
        try { action(store, path); }
        finally
        {
            store.Dispose();
            if (Directory.Exists(directory)) Directory.Delete(directory, true);
        }
    }

    private static string NewDirectory() =>
        System.IO.Path.Combine(System.IO.Path.GetTempPath(), "birkin-layout-" + Guid.NewGuid());

    private static string CaptureTrace(Action action)
    {
        var writer = new StringWriter();
        var listener = new TextWriterTraceListener(writer);
        Trace.Listeners.Add(listener);
        try
        {
            action();
            Trace.Flush();
            return writer.ToString();
        }
        finally
        {
            Trace.Listeners.Remove(listener);
            listener.Dispose();
        }
    }

    private static string CaptureTrace<T>(Func<T> action, out T result)
    {
        T captured = default!;
        var trace = CaptureTrace(() => captured = action());
        result = captured;
        return trace;
    }

    private static int Count(string text, string value) =>
        (text.Length - text.Replace(value, string.Empty, StringComparison.Ordinal).Length) / value.Length;
}
