using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Presentation;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class ImportedFilePresentationTests
{
    [TestMethod]
    public void TryFromReceipt_WhenReferenceIsValid_ParsesBoundedChip()
    {
        var parsed = ImportedFilePresentationMapper.TryFromReceipt(
            Receipt(Reference()),
            out var imported);

        Assert.IsTrue(parsed);
        Assert.IsNotNull(imported);
        Assert.AreEqual("import-1", imported.ImportId);
        Assert.AreEqual("first-report.xlsx", imported.DisplayName);
        Assert.AreEqual(1200L, imported.ByteCount);
    }

    [DataTestMethod]
    [DataRow("missing-import-id")]
    [DataRow("long-import-id")]
    [DataRow("control-display-name")]
    [DataRow("long-display-name")]
    [DataRow("invalid-jail-name")]
    [DataRow("short-sha256")]
    [DataRow("uppercase-sha256")]
    [DataRow("negative-byte-count")]
    public void TryFromReceipt_WhenReferenceIsMalformed_RejectsWithoutThrowing(
        string variant)
    {
        var parsed = ImportedFilePresentationMapper.TryFromReceipt(
            Receipt(Reference(variant)),
            out var imported);

        Assert.IsFalse(parsed);
        Assert.IsNull(imported);
    }

    private static NativeJsonObject Reference(string? variant = null)
    {
        List<(string Key, NativeJsonValue Value)> pairs =
        [
            ("kind", new NativeJsonString("workspace_import")),
            ("import_id", new NativeJsonString(
                variant == "long-import-id"
                    ? new string('i', 129)
                    : "import-1")),
            ("display_name", new NativeJsonString(variant switch
            {
                "control-display-name" => "first\nreport.xlsx",
                "long-display-name" => new string('a', 256),
                _ => "first-report.xlsx",
            })),
            ("jail_name", new NativeJsonString(
                variant == "invalid-jail-name"
                    ? "../first-report.xlsx"
                    : "import-1.xlsx")),
            ("sha256", new NativeJsonString(variant switch
            {
                "short-sha256" => new string('a', 63),
                "uppercase-sha256" => new string('A', 64),
                _ => new string('a', 64),
            })),
            ("byte_count", new NativeJsonInteger(
                variant == "negative-byte-count" ? -1 : 1200)),
        ];
        if (variant == "missing-import-id")
        {
            pairs.RemoveAt(1);
        }
        return Object([.. pairs]);
    }

    private static NativeEnvelope Receipt(NativeJsonObject reference) => new(
        NativeMessageKind.Receipt,
        "receipt-1",
        Object(
            ("result", Object(("reference", reference)))));

    private static NativeJsonObject Object(
        params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair =>
            new KeyValuePair<string, NativeJsonValue>(
                pair.Key,
                pair.Value)));
}
