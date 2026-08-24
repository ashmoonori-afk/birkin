using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Support;

[TestClass]
public sealed class BridgeStandardErrorCaptureTests
{
    [TestMethod]
    public void Append_WhenUvEmitsKnownLauncherProgress_SeparatesItFromBridgeStandardError()
    {
        // Given
        string[] diagnostics =
        [
            "   Building birkin @ file:///C:/workspace/birkin",
            "      Built birkin @ file:///C:/workspace/birkin",
            "Uninstalled 1 package in 119ms",
            "Installed 1 package in 244ms",
            "Resolved 12 packages in 1.2s",
            "Audited 12 packages in 8ms",
        ];
        var capture = new BridgeStandardErrorCapture();

        // When
        foreach (var line in diagnostics)
        {
            capture.Append(line);
        }

        // Then
        Assert.AreEqual(string.Empty, capture.StandardError);
        Assert.AreEqual(string.Join(Environment.NewLine, diagnostics), capture.LauncherDiagnostics);
    }

    [TestMethod]
    public void Append_WhenUnexpectedLineIsInjected_FailsWithRedactedBridgeDiagnostics()
    {
        // Given
        const string unexpected = "E_BRIDGE_SENTINEL unexpected bridge failure";
        var capture = new BridgeStandardErrorCapture();
        capture.Append(unexpected);

        // When
        var failure = Assert.ThrowsException<AssertFailedException>(() =>
            RedactedDiagnostics.AssertEmpty("bridge_stderr", capture.StandardError));

        // Then
        StringAssert.Contains(failure.Message, $"bridge_stderr_bytes={System.Text.Encoding.UTF8.GetByteCount(unexpected)}");
        StringAssert.Contains(failure.Message, $"bridge_stderr_sha256={ProviderOfficeEvidence.Hash(unexpected)}");
        Assert.IsFalse(failure.Message.Contains(unexpected, StringComparison.Ordinal));
        Assert.AreEqual(string.Empty, capture.LauncherDiagnostics);
    }
}
