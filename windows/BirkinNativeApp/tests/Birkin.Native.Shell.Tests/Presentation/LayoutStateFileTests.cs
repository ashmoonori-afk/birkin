using System.Text.Json;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Presentation;

[TestClass]
public sealed class LayoutStateFileTests
{
    [TestMethod]
    public void RoundTrip_DefaultAndModifiedStates_PreservesValues()
    {
        var modified = LayoutState.Default with
        {
            Navigation = new LayoutColumnState(360, false),
            Context = new LayoutColumnState(420, true),
            LastTouched = LayoutPanel.Navigation,
            FocusRestore = new LayoutFocusRestore(true, false),
            Window = new LayoutWindowState(1300, 800, 20, 30, LayoutWindowMode.Maximized),
            Hints = new LayoutHintsState(true),
        };

        Assert.AreEqual(LayoutState.Default, LayoutFile.Parse(LayoutFile.Serialize(LayoutState.Default)));
        Assert.AreEqual(modified, LayoutFile.Parse(LayoutFile.Serialize(modified)));
        using var document = JsonDocument.Parse(LayoutFile.Serialize(modified));
        Assert.AreEqual(1, document.RootElement.GetProperty("version").GetInt32());
    }

    [DataTestMethod]
    [DataRow("")]
    [DataRow("   \r\n")]
    [DataRow("{not json")]
    [DataRow("{}")]
    [DataRow("{\"version\":99}")]
    [DataRow("{\"version\":\"1\"}")]
    public void Parse_InvalidDocument_UsesAllDefaults(string json) =>
        Assert.AreEqual(LayoutState.Default, LayoutFile.Parse(json));

    [DataTestMethod]
    [DataRow("50", 240.0)]
    [DataRow("5000", 480.0)]
    [DataRow("\"abc\"", 280.0)]
    [DataRow("\"NaN\"", 280.0)]
    [DataRow("-1", 280.0)]
    public void Parse_NavigationWidth_AppliesFieldFallback(string value, double expected)
    {
        var state = LayoutFile.Parse("{\"version\":1,\"columns\":{\"navigation\":{\"width\":" + value + ",\"visible\":true}}}");
        Assert.AreEqual(expected, state.Navigation.Width);
        Assert.AreEqual(LayoutState.Default.Context, state.Context);
    }

    [DataTestMethod]
    [DataRow("50", 300.0)]
    [DataRow("5000", 600.0)]
    [DataRow("\"abc\"", 340.0)]
    [DataRow("\"Infinity\"", 340.0)]
    [DataRow("-1", 340.0)]
    public void Parse_ContextWidth_AppliesFieldFallback(string value, double expected)
    {
        var state = LayoutFile.Parse("{\"version\":1,\"columns\":{\"context\":{\"width\":" + value + ",\"visible\":true}}}");
        Assert.AreEqual(expected, state.Context.Width);
        Assert.AreEqual(LayoutState.Default.Navigation, state.Navigation);
    }

    [DataTestMethod]
    [DataRow("1e308", 16384.0)]
    [DataRow("16384", 16384.0)]
    [DataRow("-1", 640.0)]
    [DataRow("\"wide\"", 1500.0)]
    public void Parse_WindowWidth_ClampsFiniteValuesAndDefaultsNonnumeric(string value, double expected)
    {
        var state = LayoutFile.Parse("{\"version\":1,\"window\":{\"width\":" + value + "}}");
        Assert.AreEqual(expected, state.Window.Width);
    }

    [DataTestMethod]
    [DataRow("1e308", 16384.0)]
    [DataRow("16384", 16384.0)]
    [DataRow("-1", 480.0)]
    [DataRow("\"tall\"", 940.0)]
    public void Parse_WindowHeight_ClampsFiniteValuesAndDefaultsNonnumeric(string value, double expected)
    {
        var state = LayoutFile.Parse("{\"version\":1,\"window\":{\"height\":" + value + "}}");
        Assert.AreEqual(expected, state.Window.Height);
    }

    [TestMethod]
    public void Parse_BadFields_DefaultIndependently()
    {
        var state = LayoutFile.Parse("""{"version":1,"columns":{"navigation":[],"context":{"width":410,"visible":"yes"}},"lastTouched":"bad","focusRestore":{"navigation":true},"window":{"width":900,"height":600,"left":12,"top":13,"state":"Minimized"},"hints":{"layoutTipShown":"yes"}}""");

        Assert.AreEqual(LayoutState.Default.Navigation, state.Navigation);
        Assert.AreEqual(new LayoutColumnState(410, true), state.Context);
        Assert.AreEqual(LayoutPanel.Context, state.LastTouched);
        Assert.IsNull(state.FocusRestore);
        Assert.AreEqual(900, state.Window.Width);
        Assert.AreEqual(600, state.Window.Height);
        Assert.AreEqual(LayoutWindowMode.Normal, state.Window.State);
        Assert.IsFalse(state.Hints.LayoutTipShown);
    }
}
