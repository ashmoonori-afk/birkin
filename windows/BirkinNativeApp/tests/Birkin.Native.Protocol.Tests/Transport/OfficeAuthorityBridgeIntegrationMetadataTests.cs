using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Transport;

[TestClass]
public sealed class OfficeAuthorityBridgeIntegrationMetadataTests
{
    [TestMethod]
    public void IntegrationTest_IsCategorizedForPortableExclusionAndWindowsFullSuite()
    {
        var categories = typeof(OfficeAuthorityBridgeIntegrationTests)
            .GetCustomAttributes(typeof(TestCategoryAttribute), inherit: true)
            .Cast<TestCategoryAttribute>()
            .SelectMany(attribute => attribute.TestCategories)
            .ToArray();

        CollectionAssert.Contains(categories, "LiveBridge");
        CollectionAssert.Contains(categories, "WindowsOnly");
    }
}
