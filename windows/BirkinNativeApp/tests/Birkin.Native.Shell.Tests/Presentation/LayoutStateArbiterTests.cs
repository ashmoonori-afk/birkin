using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Presentation;

[TestClass]
public sealed class LayoutStateArbiterTests
{
    [TestMethod]
    public void Resolve_DefaultLayout_KeepsSideWidthsAndAssignsRemainderToPrimary()
    {
        var result = LayoutArbiter.Resolve(LayoutState.Default, 1500);
        Assert.AreEqual(280, result.NavigationWidth);
        Assert.AreEqual(340, result.ContextWidth);
        Assert.AreEqual(844, result.PrimaryWidth);
    }

    [TestMethod]
    public void Resolve_MaximumWidthsAtMinimumWindow_ShrinksLastTouchedFirst()
    {
        var state = LayoutState.Default with
        {
            Navigation = new LayoutColumnState(480, true),
            Context = new LayoutColumnState(600, true),
            LastTouched = LayoutPanel.Context,
        };
        var result = LayoutArbiter.Resolve(state, 1100);
        Assert.AreEqual(364, result.NavigationWidth);
        Assert.AreEqual(300, result.ContextWidth);
        Assert.AreEqual(400, result.PrimaryWidth);
    }

    [TestMethod]
    public void Resolve_WhenNavigationWasLastTouched_ShrinksNavigationFirst()
    {
        var state = LayoutState.Default with
        {
            Navigation = new LayoutColumnState(480, true),
            Context = new LayoutColumnState(600, true),
            LastTouched = LayoutPanel.Navigation,
        };
        var result = LayoutArbiter.Resolve(state, 1100);
        Assert.AreEqual(240, result.NavigationWidth);
        Assert.AreEqual(424, result.ContextWidth);
        Assert.AreEqual(400, result.PrimaryWidth);
    }

    [TestMethod]
    public void Resolve_HiddenPanelsUseNoWidthOrSplitter()
    {
        var state = LayoutState.Default with { Navigation = new LayoutColumnState(360, false) };
        var result = LayoutArbiter.Resolve(state, 1100);
        Assert.AreEqual(0, result.NavigationWidth);
        Assert.AreEqual(340, result.ContextWidth);
        Assert.AreEqual(730, result.PrimaryWidth);
        Assert.AreEqual(1, result.SplitterCount);
    }
}
