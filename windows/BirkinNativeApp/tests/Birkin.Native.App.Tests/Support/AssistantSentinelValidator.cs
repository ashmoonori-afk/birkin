using System.Text;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Support;

internal sealed record AssistantSentinelRow(string Id, string Text);

internal static class AssistantSentinelValidator
{
    public static AssistantSentinelRow ValidateExact(
        IReadOnlyList<AssistantSentinelRow> rows,
        string expectedSentinel,
        string expectedSha256)
    {
        var configuredHash = ProviderOfficeEvidence.Hash(expectedSentinel);
        if (!string.Equals(configuredHash, expectedSha256, StringComparison.Ordinal))
        {
            throw new AssertFailedException("assistant sentinel validation failed; configured_expected_hash_mismatch=true");
        }

        if (rows.Count != 1)
        {
            var rowDiagnostics = rows.Count == 0
                ? string.Empty
                : "; " + string.Join("; ", rows.Select(Describe));
            throw new AssertFailedException(
                $"assistant sentinel validation failed; assistant_row_count={rows.Count}; expected_exactly_one=true{rowDiagnostics}");
        }

        var row = rows[0];
        var trimmed = row.Text.Trim();
        var actualHash = ProviderOfficeEvidence.Hash(trimmed);
        if (!string.Equals(trimmed, expectedSentinel, StringComparison.Ordinal)
            || !string.Equals(actualHash, expectedSha256, StringComparison.Ordinal))
        {
            throw new AssertFailedException(
                $"assistant sentinel validation failed; {Describe(row)}; expected_hash_mismatch=true");
        }

        return row;
    }

    private static string Describe(AssistantSentinelRow row)
    {
        var trimmed = row.Text.Trim();
        return $"row_id={row.Id}; text_bytes={Encoding.UTF8.GetByteCount(trimmed)}; "
            + $"text_sha256={ProviderOfficeEvidence.Hash(trimmed)}";
    }
}
