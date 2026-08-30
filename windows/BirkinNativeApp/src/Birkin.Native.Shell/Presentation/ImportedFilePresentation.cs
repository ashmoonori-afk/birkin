using System.Globalization;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Shell.Presentation;

public sealed record ImportedFilePresentation(
    string ImportId,
    string DisplayName,
    string JailName,
    string Sha256,
    long ByteCount)
{
    public string AccessibleName => $"{DisplayName}, {ByteCount} bytes";
}

public static class ImportedFilePresentationMapper
{
    private static readonly IReadOnlySet<string> ReferenceKeys =
        new HashSet<string>(
            [
                "kind",
                "import_id",
                "display_name",
                "jail_name",
                "sha256",
                "byte_count",
            ],
            StringComparer.Ordinal);

    public static bool TryFromReceipt(
        NativeEnvelope receipt,
        out ImportedFilePresentation? imported)
    {
        imported = null;
        if (receipt.Kind != NativeMessageKind.Receipt
            || receipt.Body["result"] is not NativeJsonObject result
            || result["reference"] is not NativeJsonObject reference)
        {
            return true;
        }
        if (reference.Count != ReferenceKeys.Count
            || reference.Keys.Any(key => !ReferenceKeys.Contains(key))
            || Text(reference, "kind") != "workspace_import"
            || Text(reference, "import_id") is not { } importId
            || !IsIdentifier(importId)
            || Text(reference, "display_name") is not { } displayName
            || !IsDisplayName(displayName)
            || Text(reference, "jail_name") is not { } jailName
            || !IsJailName(jailName)
            || Text(reference, "sha256") is not { } sha256
            || !IsSha256(sha256)
            || reference["byte_count"] is not NativeJsonInteger
            {
                Value: >= 0,
            } bytes)
        {
            return false;
        }

        imported = new ImportedFilePresentation(
            importId,
            displayName,
            jailName,
            sha256,
            bytes.Value);
        return true;
    }

    private static string? Text(NativeJsonObject value, string key) =>
        value[key] is NativeJsonString text ? text.Value : null;

    private static bool IsIdentifier(string value) =>
        value.Length is >= 1 and <= 128
        && value.All(character =>
            character is (>= 'A' and <= 'Z')
                or (>= 'a' and <= 'z')
                or (>= '0' and <= '9')
                or '.' or '_' or ':' or '-');

    private static bool IsDisplayName(string value) =>
        value.Length is >= 1 and <= 255
        && value.All(character =>
            !char.IsControl(character)
            && CharUnicodeInfo.GetUnicodeCategory(character)
                != UnicodeCategory.Format);

    private static bool IsJailName(string value) =>
        value.Length is >= 1 and <= 255
        && value.All(character =>
            character is (>= 'A' and <= 'Z')
                or (>= 'a' and <= 'z')
                or (>= '0' and <= '9')
                or '.' or '_' or '-');

    private static bool IsSha256(string value) =>
        value.Length == 64
        && value.All(character =>
            character is (>= '0' and <= '9')
                or (>= 'a' and <= 'f'));
}
