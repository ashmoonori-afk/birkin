using System.Text;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Support;

internal static class RedactedDiagnostics
{
    public static void AssertEmpty(string name, string value)
    {
        if (value.Length == 0)
        {
            return;
        }

        throw new AssertFailedException(
            $"{name} was non-empty; {name}_bytes={Encoding.UTF8.GetByteCount(value)}; "
            + $"{name}_sha256={ProviderOfficeEvidence.Hash(value)}");
    }
}
