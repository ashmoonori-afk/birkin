using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Presentation;

[TestClass]
public sealed class ApprovalAttentionTrackerTests
{
    [TestMethod]
    public void Observe_WhenApprovalRemainsPending_NotifiesExactlyOnce()
    {
        var tracker = new ApprovalAttentionTracker();
        var pending = new PanelItemPresentation(
            "approval-1",
            "approval",
            "UNTRUSTED approval title");

        var first = tracker.Observe([pending]);
        var repeated = tracker.Observe([pending]);
        var resolved = tracker.Observe([pending with { Decided = true }]);
        var next = tracker.Observe([
            pending with { Decided = true },
            new PanelItemPresentation("approval-2", "approval", "Another title"),
        ]);

        Assert.IsNotNull(first);
        Assert.AreEqual("approval-1", first.ApprovalId);
        Assert.IsNull(repeated);
        Assert.IsNull(resolved);
        Assert.IsNotNull(next);
        Assert.AreEqual("approval-2", next.ApprovalId);
        Assert.AreEqual(1, tracker.PendingCount);
    }

    [TestMethod]
    public void ToastContent_WhenApprovalIsUntrusted_IsFixedAndNavigationOnly()
    {
        var content = ApprovalToastContent.For("opaque-approval-1");

        Assert.AreEqual("승인 요청이 도착했습니다", content.Title);
        Assert.AreEqual("Birkin에서 요청 내용을 확인하세요.", content.Body);
        Assert.AreEqual("opaque-approval-1", content.ApprovalId);
        Assert.AreEqual("approvals", content.Route);
        Assert.AreEqual(0, content.DecisionActions.Count);
    }
}
