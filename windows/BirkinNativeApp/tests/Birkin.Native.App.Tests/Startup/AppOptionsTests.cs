using System.IO;
using Birkin.Native.App.Startup;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Startup;

[TestClass]
public sealed class AppOptionsTests
{
    [TestMethod]
    public void Parse_WhenAnnouncementFileContainsOneJsonLine_ReturnsThatLine()
    {
        // Given
        using var file = TemporaryFile.Create("{\"event\":\"listening\"}\n");

        // When
        var options = AppOptions.Parse(["--bridge-announcement-file", file.Path]);

        // Then
        Assert.AreEqual("{\"event\":\"listening\"}", options.BridgeAnnouncementJson);
    }

    [TestMethod]
    public void Parse_WhenNoAnnouncementWasSupplied_SelectsOwnedBridgeMode()
    {
        var options = AppOptions.Parse([]);

        Assert.IsFalse(options.IsAttached);
        Assert.AreEqual(string.Empty, options.BridgeAnnouncementJson);
    }

    [DataTestMethod]
    [DataRow("--bridge-announcement-file")]
    [DataRow("--bridge-announcement-file", "relative.json")]
    [DataRow("--unknown", "value")]
    public void Parse_WhenArgumentsDoNotIdentifyOneAbsoluteFile_RejectsArguments(params string[] arguments)
    {
        // Given / When
        var action = () => AppOptions.Parse(arguments);

        // Then
        Assert.ThrowsException<ArgumentException>(action);
    }

    [TestMethod]
    public void Parse_WhenOptionIsRepeated_RejectsArguments()
    {
        // Given
        using var first = TemporaryFile.Create("{}\n");
        using var second = TemporaryFile.Create("{}\n");

        // When
        var action = () => AppOptions.Parse([
            "--bridge-announcement-file", first.Path,
            "--bridge-announcement-file", second.Path,
        ]);

        // Then
        Assert.ThrowsException<ArgumentException>(action);
    }

    [DataTestMethod]
    [DataRow("")]
    [DataRow("\n\r\n")]
    [DataRow("{}\n{\"second\":true}\n")]
    public void Parse_WhenFileDoesNotContainExactlyOneNonblankLine_RejectsFile(string content)
    {
        // Given
        using var file = TemporaryFile.Create(content);

        // When
        var action = () => AppOptions.Parse(["--bridge-announcement-file", file.Path]);

        // Then
        Assert.ThrowsException<ArgumentException>(action);
    }

    private sealed class TemporaryFile : IDisposable
    {
        private TemporaryFile(string path) => Path = path;

        public string Path { get; }

        public static TemporaryFile Create(string content)
        {
            var path = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"birkin-app-options-{Guid.NewGuid():N}.jsonl");
            File.WriteAllText(path, content);
            return new TemporaryFile(path);
        }

        public void Dispose() => File.Delete(Path);
    }
}
