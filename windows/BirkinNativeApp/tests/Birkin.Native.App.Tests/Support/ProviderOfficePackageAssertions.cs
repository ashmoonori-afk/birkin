using System.IO;
using System.IO.Compression;
using System.Text;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Support;

internal static class ProviderOfficePackageAssertions
{
    public static void AssertSpreadsheet(string path, string value)
    {
        Assert.IsTrue(File.Exists(path), $"spreadsheet does not exist: {Path.GetFileName(path)}");
        var xml = ReadPackageXml(path);
        StringAssert.Contains(xml, "BIRKIN_P3_03_SENTINEL");
        StringAssert.Contains(xml, value);
        using var package = ZipFile.OpenRead(path);
        Assert.IsTrue(package.GetEntry("[Content_Types].xml") is not null);
        Assert.IsTrue(package.Entries.Any(entry => entry.FullName.StartsWith("xl/worksheets/", StringComparison.Ordinal)));
    }

    public static void AssertReport(string path)
    {
        Assert.IsTrue(File.Exists(path), "approved report was not saved");
        var xml = ReadPackageXml(path);
        StringAssert.Contains(xml, "BIRKIN_P3_03_DOCUMENT_SENTINEL");
        StringAssert.Contains(xml, "4100");
        StringAssert.Contains(xml, "4700");
        using var package = ZipFile.OpenRead(path);
        Assert.IsTrue(package.GetEntry("[Content_Types].xml") is not null);
        Assert.IsTrue(package.GetEntry("word/document.xml") is not null);
    }

    private static string ReadPackageXml(string path)
    {
        using var package = ZipFile.OpenRead(path);
        return string.Join("\n", package.Entries
            .Where(entry => entry.FullName.EndsWith(".xml", StringComparison.Ordinal))
            .Select(ReadEntry));
    }

    private static string ReadEntry(ZipArchiveEntry entry)
    {
        using var reader = new StreamReader(entry.Open(), Encoding.UTF8);
        return reader.ReadToEnd();
    }
}
