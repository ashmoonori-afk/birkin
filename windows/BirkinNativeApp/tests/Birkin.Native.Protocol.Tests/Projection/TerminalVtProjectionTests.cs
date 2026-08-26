using System.Reflection;
using Birkin.Native.Protocol.Projection;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Projection;

[TestClass]
public sealed class TerminalVtProjectionTests
{
    private const int DisplayBudget = 65_536;

    [TestMethod]
    public void Reduce_WhenCsiSgrAndCjkAreSplitAcrossChunks_PreservesParserStateImmutably()
    {
        // Given
        var initial = NewState();

        // When
        var afterCsiPrefix = Reduce(initial, "left \u001b[3");
        var afterCsi = Reduce(afterCsiPrefix, "1m한");
        var afterCjk = Reduce(afterCsi, "글-日本語\u001b[0m right");

        // Then
        Assert.AreNotSame(initial, afterCsiPrefix);
        Assert.AreNotSame(afterCsiPrefix, afterCsi);
        Assert.AreNotSame(afterCsi, afterCjk);
        Assert.AreEqual(string.Empty, Display(initial));
        Assert.AreEqual("left ", Display(afterCsiPrefix));
        Assert.AreEqual("left 한", Display(afterCsi));
        Assert.AreEqual("left 한글-日本語 right", Display(afterCjk));
    }

    [TestMethod]
    public void Reduce_WhenOscTerminatorsAreSplitAcrossChunks_ConsumesBelAndStPayloads()
    {
        // Given
        var state = NewState();

        // When
        var afterBelPrefix = Reduce(state, "A\u001b]0;private-title");
        var afterBel = Reduce(afterBelPrefix, "\u0007B");
        var afterStPrefix = Reduce(afterBel, "\u001b]2;other-private\u001b");
        var afterSt = Reduce(afterStPrefix, "\\C");

        // Then
        Assert.AreEqual("A", Display(afterBelPrefix));
        Assert.AreEqual("AB", Display(afterBel));
        Assert.AreEqual("AB", Display(afterStPrefix));
        Assert.AreEqual("ABC", Display(afterSt));
    }

    [TestMethod]
    public void Render_WhenCursorAndEditingControlsArePresent_ProducesTerminalDisplay()
    {
        // Given
        const string stream =
            "ABCDE\r\u001b[3C\u001b[KZ" +
            "\r\n12345\bX" +
            "\r\nA\tB" +
            "\u001b[1;2HZ";

        // When
        var display = Render(stream);

        // Then
        Assert.AreEqual("AZCZ\n1234X\nA       B", display);
    }

    [TestMethod]
    public void Render_WhenLfAppearsWithoutCr_MovesDownWithoutResettingColumn()
    {
        // Given
        const string stream = "A\nB";

        // When
        var display = Render(stream);

        // Then
        Assert.AreEqual("A\n B", display);
    }

    [TestMethod]
    public void Render_WhenEraseDisplaySgrAndUnknownControlsArePresent_ConsumesControlsWithoutRawEscapeText()
    {
        // Given
        const string stream =
            "old-content\u001b[2J\u001b[H" +
            "\u001b[38;5;196mSAFE\u001b[0m" +
            "\u001b[?9999h\u001b[777z\u0000";

        // When
        var display = Render(stream);

        // Then
        Assert.AreEqual("SAFE", display);
        Assert.IsFalse(display.Contains('\u001b'));
        Assert.IsFalse(display.Contains("9999", StringComparison.Ordinal));
        Assert.IsFalse(display.Contains("777", StringComparison.Ordinal));
    }

    [TestMethod]
    public void Render_WhenStreamExceedsPresentationBudget_KeepsBoundedNewestDisplay()
    {
        // Given
        var stream = "discard-prefix-731" + new string('x', DisplayBudget - 3) + "END";

        // When
        var display = Render(stream);

        // Then
        Assert.AreEqual(DisplayBudget, display.Length);
        Assert.IsFalse(display.StartsWith("discard-prefix-731", StringComparison.Ordinal));
        Assert.IsTrue(display.EndsWith("END", StringComparison.Ordinal));
    }

    private static object NewState()
    {
        var stateType = ProjectionAssembly().GetType(
            "Birkin.Native.Protocol.Projection.TerminalVtState",
            throwOnError: false);
        Assert.IsNotNull(stateType, "TerminalVtState must exist for immutable split-event reduction");
        var state = Activator.CreateInstance(stateType);
        Assert.IsNotNull(state, "TerminalVtState must have an empty public constructor");
        return state;
    }

    private static object Reduce(object state, string chunk)
    {
        var projectionType = ProjectionType();
        var method = projectionType.GetMethod(
            "Reduce",
            BindingFlags.Public | BindingFlags.Static,
            binder: null,
            types: [state.GetType(), typeof(string)],
            modifiers: null);
        Assert.IsNotNull(method, "TerminalVtProjection.Reduce(TerminalVtState, string) must exist");
        return method.Invoke(null, [state, chunk])
            ?? throw new AssertFailedException("TerminalVtProjection.Reduce returned null");
    }

    private static string Render(string stream)
    {
        var method = ProjectionType().GetMethod(
            "Render",
            BindingFlags.Public | BindingFlags.Static,
            binder: null,
            types: [typeof(string)],
            modifiers: null);
        Assert.IsNotNull(method, "TerminalVtProjection.Render(string) must exist");
        return method.Invoke(null, [stream]) as string
            ?? throw new AssertFailedException("TerminalVtProjection.Render must return a string");
    }

    private static string Display(object state)
    {
        var property = state.GetType().GetProperty("Display", BindingFlags.Instance | BindingFlags.Public);
        Assert.IsNotNull(property, "TerminalVtState must expose immutable Display state");
        return property.GetValue(state) as string
            ?? throw new AssertFailedException("TerminalVtState.Display must be a string");
    }

    private static Type ProjectionType()
    {
        var type = ProjectionAssembly().GetType(
            "Birkin.Native.Protocol.Projection.TerminalVtProjection",
            throwOnError: false);
        Assert.IsNotNull(type, "TerminalVtProjection must exist");
        return type;
    }

    private static Assembly ProjectionAssembly() => typeof(NativeProjectionStore).Assembly;
}
