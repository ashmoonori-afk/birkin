using Birkin.Native.Protocol.Projection;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Projection;

[TestClass]
public sealed class TerminalVtRealConptyStreamTests
{
    private const string Prompt = "P>";

    [TestMethod]
    public void Render_ExactSafeResizedConptyShape_KeepsCjkAdjacentToPrompt()
    {
        // Given
        var stream = SafeResizedStream("echo 한글-日本語");

        // When
        var display = TerminalVtProjection.Render(stream, 100, 30);

        // Then
        StringAssert.Contains(display, Prompt + "echo 한글-日本語");
        Assert.IsFalse(display.Contains(Prompt + " " + "echo 한글-日本語", StringComparison.Ordinal));
        Assert.IsTrue(display.Split('\n').All(line => CellWidth(line) <= 100));
    }

    [TestMethod]
    public void Render_ExactSafeResizedConptyShape_AttachesDecomposedMark()
    {
        // Given
        var stream = SafeDelayedStream("echo e\u0301");

        // When
        var display = TerminalVtProjection.Render(stream, 100, 30);

        // Then
        StringAssert.Contains(display, Prompt + "echo e\u0301");
        Assert.AreEqual(6, CellWidth("echo e\u0301"));
    }

    private static string SafeResizedStream(string command)
    {
        var stream = new System.Text.StringBuilder()
            .Append("\u001b[?9001h\u001b[?1004h\u001b[?25l\u001b[2J\u001b[m\u001b[H")
            .Append('A', 43).Append("\u001b]0;<PATH>\a\u001b[?25h\u001b[?25l\r\n")
            .Append('B', 47).Append("\u001b[4;1H").Append('P', 55)
            .Append("\u001b[?25h\u001b[?25l\u001b[8;30;100t\u001b[H")
            .Append('A', 43).Append("\u001b[K\r\n").Append('B', 47).Append("\u001b[K\r\n");
        for (var row = 0; row < 28; row++) stream.Append("\u001b[K\r\n");
        return stream.Append("\u001b[K\u001b[4;56H").Append(Prompt).Append(command)
            .Append("\r\n한글-日本語\u001b[7;1H").Append('P', 55).ToString();
    }

    private static string SafeDelayedStream(string command) =>
        new string('x', 100) + "\u0301" + Prompt + command;

    private static int CellWidth(string value) => value.EnumerateRunes().Sum(rune =>
        rune.Value == 0x301 ? 0
        : rune.Value is >= 0x1100 and <= 0x115f
            or >= 0x2e80 and <= 0xa4cf
            or >= 0xac00 and <= 0xd7a3
            or >= 0xf900 and <= 0xfaff
            or >= 0xff00 and <= 0xff60 ? 2 : 1);
}
