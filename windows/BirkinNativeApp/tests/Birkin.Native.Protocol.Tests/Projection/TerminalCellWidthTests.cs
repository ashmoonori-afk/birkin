using System.Reflection;
using System.Text;
using Birkin.Native.Protocol.Projection;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Projection;

[TestClass]
public sealed class TerminalCellWidthTests
{
    [TestMethod]
    public void Width_UsesZeroOneTwoTerminalCells()
    {
        // Given
        var width = WidthMethod();
        var cases = new (Rune Rune, int Width)[]
        {
            (new Rune('\u0301'), 0), (new Rune('\ufe0f'), 0), (new Rune(0xe0100), 0),
            (new Rune('A'), 1), (new Rune('\u00b7'), 1),
            (new Rune('\ud55c'), 2), (new Rune('\u65e5'), 2), (new Rune('\u30ab'), 2),
            (new Rune('\uff21'), 2), (new Rune(0x1f680), 2),
        };

        // When / Then
        foreach (var item in cases)
        {
            Assert.AreEqual(item.Width, width.Invoke(null, [item.Rune]), $"U+{item.Rune.Value:X}");
        }
    }

    [TestMethod]
    public void Render_WideAndCombiningRunesHonorCellAddressedCursorEditing()
    {
        // Given
        const string stream = "A\ud55c\u0301B\bX\r\u001b[3CZ\u001b[2GQ\r\nA\ud55cB\r\u001b[3GQ\r\n\ud55cX\r\u001b[3G\u001b[K";

        // When
        var display = TerminalVtProjection.Render(stream);

        // Then
        Assert.AreEqual("AQ Z\nA QB\n\ud55c", display);
    }

    [TestMethod]
    public void Render_CjkCommandDoesNotDriftAcrossCellColumns()
    {
        // Given
        const string command = "echo \ud55c\uae00-\u65e5\u672c\u8a9e";
        var stream = command + "\r\u001b[17G>\r\nCONPTY_OK";

        // When
        var display = TerminalVtProjection.Render(stream);

        // Then
        Assert.AreEqual(command + ">\nCONPTY_OK", display);
    }

    private static MethodInfo WidthMethod()
    {
        var type = typeof(NativeProjectionStore).Assembly.GetType(
            "Birkin.Native.Protocol.Projection.TerminalCellWidth",
            throwOnError: false);
        Assert.IsNotNull(type, "TerminalCellWidth must be the sole cell-width policy");
        var method = type.GetMethod("Width", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
        Assert.IsNotNull(method, "TerminalCellWidth.Width(Rune) must exist");
        return method;
    }
}
