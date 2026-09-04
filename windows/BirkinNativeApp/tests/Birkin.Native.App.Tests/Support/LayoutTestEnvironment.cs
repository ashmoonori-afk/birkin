using System.IO;
using Birkin.Native.App.Startup;
using Microsoft.VisualStudio.TestTools.UnitTesting;

[assembly: Parallelize(Workers = 1, Scope = ExecutionScope.MethodLevel)]

namespace Birkin.Native.App.Tests.Support;

[TestClass]
public sealed class LayoutTestAssemblyEnvironment
{
    [AssemblyInitialize]
    public static void Initialize(TestContext context) => LayoutTestEnvironment.Initialize();

    [AssemblyCleanup]
    public static void Cleanup() => LayoutTestEnvironment.Cleanup();
}

public abstract class MainWindowTestBase
{
    [TestInitialize]
    public void ResetPersistedLayout() => LayoutTestEnvironment.Reset();
}

internal static class LayoutTestEnvironment
{
    private static string? _originalPath;
    private static string? _directory;

    internal static string LayoutPath => System.IO.Path.Combine(
        _directory ?? throw new InvalidOperationException("The layout test environment is not initialized."),
        "layout.json");

    internal static void Initialize()
    {
        _originalPath = Environment.GetEnvironmentVariable(LayoutStore.EnvironmentVariableName);
        _directory = System.IO.Path.Combine(
            System.IO.Path.GetTempPath(),
            $"birkin-app-tests-{Environment.ProcessId}-{Guid.NewGuid():N}");
        Reset();
    }

    internal static void Reset()
    {
        Environment.SetEnvironmentVariable(LayoutStore.EnvironmentVariableName, LayoutPath);
        if (Directory.Exists(_directory)) Directory.Delete(_directory, true);
        Directory.CreateDirectory(_directory!);
    }

    internal static void Cleanup()
    {
        Environment.SetEnvironmentVariable(LayoutStore.EnvironmentVariableName, _originalPath);
        if (_directory is not null && Directory.Exists(_directory)) Directory.Delete(_directory, true);
        _directory = null;
        _originalPath = null;
    }
}
