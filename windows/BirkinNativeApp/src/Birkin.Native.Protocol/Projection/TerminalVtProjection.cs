namespace Birkin.Native.Protocol.Projection;

public sealed class TerminalVtState
{
    private readonly TerminalCellLine[] _lines;

    public TerminalVtState()
        : this([], 0, 0, TerminalVtProjection.DisplayBudget, TerminalVtProjection.DisplayBudget,
            false, TerminalVtParserMode.Text, string.Empty, null)
    {
    }

    internal TerminalVtState(
        IEnumerable<TerminalCellLine> lines,
        int cursorRow,
        int cursorColumn,
        int columns,
        int rows,
        bool wrapPending,
        TerminalVtParserMode parserMode,
        string controlBuffer,
        char? pendingHighSurrogate)
    {
        _lines = lines.Select(line => line.Clone()).ToArray();
        CursorRow = cursorRow;
        CursorColumn = cursorColumn;
        Columns = Math.Max(1, columns);
        Rows = Math.Max(1, rows);
        WrapPending = wrapPending;
        ParserMode = parserMode;
        ControlBuffer = controlBuffer;
        PendingHighSurrogate = pendingHighSurrogate;
        Display = TerminalVtEmulator.RenderLines(_lines);
    }

    public string Display { get; }
    internal int CursorRow { get; }
    internal int CursorColumn { get; }
    internal int Columns { get; }
    internal int Rows { get; }
    internal bool WrapPending { get; }
    internal TerminalVtParserMode ParserMode { get; }
    internal string ControlBuffer { get; }
    internal char? PendingHighSurrogate { get; }
    internal TerminalCellLine[] CopyLines() => _lines.Select(line => line.Clone()).ToArray();
}

internal enum TerminalVtParserMode
{
    Text,
    Escape,
    EscapeIntermediate,
    Csi,
    Osc,
    OscEscape,
}

public static class TerminalVtProjection
{
    public const int DisplayBudget = 65_536;

    public static TerminalVtState Reduce(TerminalVtState state, string chunk) =>
        Reduce(state, chunk, state.Columns, state.Rows);

    public static TerminalVtState Reduce(
        TerminalVtState state,
        string chunk,
        int columns,
        int rows)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(chunk);
        var emulator = new TerminalVtEmulator(state, columns, rows);
        emulator.Consume(chunk);
        return emulator.Freeze();
    }

    public static string Render(string fullStream) =>
        Render(fullStream, DisplayBudget, DisplayBudget);

    public static string Render(string fullStream, int columns, int rows)
    {
        ArgumentNullException.ThrowIfNull(fullStream);
        return Reduce(new TerminalVtState(), fullStream, columns, rows).Display;
    }
}
