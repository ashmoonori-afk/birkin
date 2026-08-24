using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Support;

[TestClass]
public sealed class AssistantSentinelValidatorTests
{
    private const string Sentinel = "OFFICE_PROVIDER_PARTICIPATED";
    private const string SentinelSha256 = "3f78f63495f2955c6b0499884a11d123ed6cfbefbf63aca74c5a41a16b9fd577";

    [TestMethod]
    public void ValidateExact_WhenTrimmedTextAndHashMatch_ReturnsTheOnlyRow()
    {
        var row = new AssistantSentinelRow("assistant-7", $"\r\n {Sentinel}\t");

        var validated = AssistantSentinelValidator.ValidateExact([row], Sentinel, SentinelSha256);

        Assert.AreSame(row, validated);
    }

    [TestMethod]
    [DataRow("arbitrary assistant text")]
    [DataRow("[provider-error] claude: OAuth session expired")]
    public void ValidateExact_WhenAssistantTextDoesNotMatch_FailsWithoutRawText(string text)
    {
        var row = new AssistantSentinelRow("assistant-sensitive", text);
        var hash = ProviderOfficeEvidence.Hash(text.Trim());

        var failure = Assert.ThrowsException<AssertFailedException>(() =>
            AssistantSentinelValidator.ValidateExact([row], Sentinel, SentinelSha256));

        StringAssert.Contains(failure.Message, "row_id=assistant-sensitive");
        StringAssert.Contains(failure.Message, $"text_bytes={System.Text.Encoding.UTF8.GetByteCount(text.Trim())}");
        StringAssert.Contains(failure.Message, $"text_sha256={hash}");
        StringAssert.Contains(failure.Message, "expected_hash_mismatch");
        Assert.IsFalse(failure.Message.Contains(text, StringComparison.Ordinal));
        Assert.IsFalse(failure.Message.Contains(Sentinel, StringComparison.Ordinal));
    }

    [TestMethod]
    public void ValidateExact_WhenRowsAreEmpty_FailsClosed()
    {
        var failure = Assert.ThrowsException<AssertFailedException>(() =>
            AssistantSentinelValidator.ValidateExact([], Sentinel, SentinelSha256));

        StringAssert.Contains(failure.Message, "assistant_row_count=0");
    }

    [TestMethod]
    public void ValidateExact_WhenRowsAreAmbiguous_FailsWithoutRawText()
    {
        AssistantSentinelRow[] rows =
        [
            new("assistant-1", Sentinel),
            new("assistant-2", "sensitive duplicate response"),
        ];

        var failure = Assert.ThrowsException<AssertFailedException>(() =>
            AssistantSentinelValidator.ValidateExact(rows, Sentinel, SentinelSha256));

        StringAssert.Contains(failure.Message, "assistant_row_count=2");
        StringAssert.Contains(failure.Message, "row_id=assistant-1");
        StringAssert.Contains(failure.Message, "row_id=assistant-2");
        Assert.IsFalse(failure.Message.Contains(rows[0].Text, StringComparison.Ordinal));
        Assert.IsFalse(failure.Message.Contains(rows[1].Text, StringComparison.Ordinal));
    }

    [TestMethod]
    public void ValidateExact_WhenExpectedHashDoesNotCorrespondToSentinel_FailsClosed()
    {
        var failure = Assert.ThrowsException<AssertFailedException>(() =>
            AssistantSentinelValidator.ValidateExact(
                [new AssistantSentinelRow("assistant-3", Sentinel)],
                Sentinel,
                new string('0', 64)));

        StringAssert.Contains(failure.Message, "configured_expected_hash_mismatch");
        Assert.IsFalse(failure.Message.Contains(Sentinel, StringComparison.Ordinal));
    }
}
