using System.Globalization;
using System.Text;

namespace Birkin.Native.Protocol.Projection;

internal static class TerminalCellWidth
{
    public static int Width(Rune rune)
    {
        var value = rune.Value;
        var category = Rune.GetUnicodeCategory(rune);
        if (category is UnicodeCategory.NonSpacingMark
            or UnicodeCategory.SpacingCombiningMark
            or UnicodeCategory.EnclosingMark
            || value is 0x200c or 0x200d
            || In(value, 0xfe00, 0xfe0f)
            || In(value, 0xe0100, 0xe01ef))
        {
            return 0;
        }
        return IsWide(value) ? 2 : 1;
    }

    private static bool IsWide(int value) =>
        In(value, 0x1100, 0x115f) || In(value, 0x231a, 0x231b)
        || In(value, 0x2329, 0x232a) || In(value, 0x23e9, 0x23ec)
        || value is 0x23f0 or 0x23f3 || In(value, 0x25fd, 0x25fe)
        || In(value, 0x2614, 0x2615) || In(value, 0x2648, 0x2653)
        || value is 0x267f or 0x2693 or 0x26a1 or 0x26ce or 0x26d4 or 0x26ea
        || In(value, 0x26aa, 0x26ab) || In(value, 0x26bd, 0x26be)
        || In(value, 0x26c4, 0x26c5) || In(value, 0x26f2, 0x26f3)
        || value is 0x26f5 or 0x26fa or 0x26fd or 0x2705 or 0x2728
        || value is 0x274c or 0x274e or 0x2757 or 0x27b0 or 0x27bf
        || In(value, 0x270a, 0x270b) || In(value, 0x2753, 0x2755)
        || In(value, 0x2795, 0x2797) || In(value, 0x2b1b, 0x2b1c)
        || value is 0x2b50 or 0x2b55
        || (In(value, 0x2e80, 0xa4cf) && value != 0x303f)
        || In(value, 0xac00, 0xd7a3) || In(value, 0xf900, 0xfaff)
        || In(value, 0xfe10, 0xfe19) || In(value, 0xfe30, 0xfe6f)
        || In(value, 0xff00, 0xff60) || In(value, 0xffe0, 0xffe6)
        || In(value, 0x1f300, 0x1faff) || In(value, 0x20000, 0x3fffd);

    private static bool In(int value, int start, int end) => value >= start && value <= end;
}
