using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Support;

[TestClass]
public sealed class BridgeStandardErrorClassifierTests
{
    private const string KnownWarning =
        @"C:\workspace\birkin\.venv\Lib\site-packages\pywinauto\keyboard.py:105: SyntaxWarning: invalid escape sequence '\;'" + "\n"
        + @"  option only affects the behavior of keys matching [-=[]\;',./a-zA-Z0-9 ].  Note";

    [TestMethod]
    public void Classify_KnownPywinautoInvalidEscapeWarning_SeparatesRuntimeDiagnostic()
    {
        var result = BridgeStandardErrorClassifier.Classify(KnownWarning);

        Assert.AreEqual(KnownWarning.Replace("\n", Environment.NewLine, StringComparison.Ordinal), result.RuntimeDiagnostics);
        Assert.AreEqual(string.Empty, result.UnexpectedStandardError);
    }

    [TestMethod]
    [DataRow(
        "birkin/native/office.py:137: SyntaxWarning: invalid escape sequence '\\s'\n"
        + "  _clean_non_chars = re.compile(u'[-_\\s]+')")]
    [DataRow(
        ".venv/Lib/site-packages/another_package/findbestmatch.py:137: SyntaxWarning: invalid escape sequence '\\s'\n"
        + "  _clean_non_chars = re.compile(u'[-_\\s]+')")]
    [DataRow(
        ".venv/Lib/site-packages/pywinauto/findbestmatch.py:137: DeprecationWarning: invalid escape sequence '\\s'\n"
        + "  _clean_non_chars = re.compile(u'[-_\\s]+')")]
    [DataRow(
        ".venv/Lib/site-packages/pywinauto/findbestmatch.py:137: SyntaxWarning: deprecated escape sequence '\\s'\n"
        + "  _clean_non_chars = re.compile(u'[-_\\s]+')")]
    [DataRow(
        ".venv/Lib/site-packages/pywinauto/findbestmatch.py:137: SyntaxWarning: invalid escape sequence '\\s'\n"
        + " _clean_non_chars = re.compile(u'[-_\\s]+')")]
    [DataRow(
        ".venv/Lib/site-packages/pywinauto/findbestmatch.py:137: SyntaxWarning: invalid escape sequence '\\s'\n"
        + "  _clean_non_chars = re.compile(u'[-_\\d]+')")]
    public void Classify_NonMatchingWarningGroup_RemainsUnexpected(string standardError)
    {
        var result = BridgeStandardErrorClassifier.Classify(standardError);

        Assert.AreEqual(string.Empty, result.RuntimeDiagnostics);
        Assert.AreEqual(standardError.Replace("\n", Environment.NewLine, StringComparison.Ordinal), result.UnexpectedStandardError);
    }

    [TestMethod]
    public void Classify_KnownWarningMixedWithArbitraryStandardError_PreservesArbitraryLine()
    {
        var standardError = $"{KnownWarning}\nE_BRIDGE_SENTINEL unexpected bridge failure";

        var result = BridgeStandardErrorClassifier.Classify(standardError);

        Assert.AreEqual(KnownWarning.Replace("\n", Environment.NewLine, StringComparison.Ordinal), result.RuntimeDiagnostics);
        Assert.AreEqual("E_BRIDGE_SENTINEL unexpected bridge failure", result.UnexpectedStandardError);
    }

    [TestMethod]
    public void ValidateStandardError_KnownWarningPassesButInjectedStandardErrorFails()
    {
        RealBridgeHarness.ValidateStandardError(KnownWarning);

        var failure = Assert.ThrowsException<InvalidOperationException>(() =>
            RealBridgeHarness.ValidateStandardError($"{KnownWarning}\nE_BRIDGE_SENTINEL unexpected bridge failure"));
        StringAssert.Contains(failure.Message, "E_BRIDGE_SENTINEL");
    }
}
