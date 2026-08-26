using Birkin.Native.App.Tests.Support;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Journeys;

[TestClass]
public sealed class ProviderOfficeJourneyTests
{
    [TestMethod]
    [TestCategory("OfficeWorkflow")]
    [TestCategory("ExistingAccountProvider")]
    public async Task MainWindow_ExistingAccountProviderAndPythonAuthority_CompleteOfficeApprovalJourney()
    {
        if (!string.Equals(Environment.GetEnvironmentVariable("BIRKIN_EXISTING_ACCOUNT_RUNNER"), "1", StringComparison.Ordinal))
        {
            Assert.Inconclusive("Set BIRKIN_EXISTING_ACCOUNT_RUNNER=1 on the protected Windows runner.");
        }

        await ProviderOfficeJourney.RunAsync();
    }
}
