using System.IO;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Support;

[TestClass]
public sealed class ProviderOfficeEvidenceTests
{
    [TestMethod]
    public void RecordText_WritesOnlyLengthAndSha256()
    {
        var root = Path.Combine(Path.GetTempPath(), $"birkin-provider-evidence-{Guid.NewGuid():N}");
        try
        {
            var evidence = new ProviderOfficeEvidence(root);
            const string sensitive = "provider output that must never be logged";

            evidence.RecordText("assistant", sensitive);

            var diagnostic = File.ReadAllText(evidence.DiagnosticPath);
            Assert.IsFalse(diagnostic.Contains(sensitive, StringComparison.Ordinal));
            StringAssert.Contains(diagnostic, "text_bytes");
            StringAssert.Contains(diagnostic, "text_sha256");
        }
        finally
        {
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }
}
