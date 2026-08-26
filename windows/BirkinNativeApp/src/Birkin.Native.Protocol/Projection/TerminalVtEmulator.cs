using System.Text;

namespace Birkin.Native.Protocol.Projection;

internal sealed class TerminalVtEmulator
{
    private const int MaxControlBuffer = 256;
    private readonly TerminalVtCellBuffer _buffer;
    private readonly int _columns;
    private readonly int _rows;
    private int _cursorRow;
    private int _cursorColumn;
    private bool _wrapPending;
    private TerminalVtParserMode _mode;
    private string _controlBuffer;
    private char? _pendingHighSurrogate;

    public TerminalVtEmulator(TerminalVtState state, int columns, int rows)
    {
        _columns = Math.Max(1, columns);
        _rows = Math.Max(1, rows);
        _buffer = new TerminalVtCellBuffer(state.CopyLines(), _columns, _rows);
        _cursorRow = Math.Clamp(state.CursorRow, 0, _rows - 1);
        _cursorColumn = Math.Clamp(state.CursorColumn, 0, _columns - 1);
        _wrapPending = state.WrapPending && state.Columns == _columns && state.Rows == _rows;
        _mode = state.ParserMode;
        _controlBuffer = state.ControlBuffer;
        _pendingHighSurrogate = state.PendingHighSurrogate;
    }

    public void Consume(string chunk)
    {
        foreach (var character in chunk) Consume(character);
    }

    public TerminalVtState Freeze() => new(
        _buffer.CopyLines(), _cursorRow, _cursorColumn, _columns, _rows, _wrapPending,
        _mode, _controlBuffer, _pendingHighSurrogate);

    public static string RenderLines(IEnumerable<TerminalCellLine> lines)
    {
        var rendered = lines.Select(line => line.Render()).ToList();
        while (rendered.Count > 0 && rendered[^1].Length == 0) rendered.RemoveAt(rendered.Count - 1);
        var display = string.Join('\n', rendered);
        if (display.Length <= TerminalVtProjection.DisplayBudget) return display;
        var start = display.Length - TerminalVtProjection.DisplayBudget;
        return char.IsLowSurrogate(display[start]) ? display[(start + 1)..] : display[start..];
    }

    private void Consume(char character)
    {
        switch (_mode)
        {
            case TerminalVtParserMode.Escape: ConsumeEscape(character); return;
            case TerminalVtParserMode.EscapeIntermediate:
                if (character is >= '\x30' and <= '\x7e') _mode = TerminalVtParserMode.Text;
                return;
            case TerminalVtParserMode.Csi: ConsumeCsi(character); return;
            case TerminalVtParserMode.Osc:
                if (character is '\a' or '\u009c') _mode = TerminalVtParserMode.Text;
                else if (character == '\x1b') _mode = TerminalVtParserMode.OscEscape;
                return;
            case TerminalVtParserMode.OscEscape:
                _mode = character == '\\' ? TerminalVtParserMode.Text
                    : character == '\x1b' ? TerminalVtParserMode.OscEscape : TerminalVtParserMode.Osc;
                return;
        }
        ConsumeText(character);
    }

    private void ConsumeText(char character)
    {
        if (_pendingHighSurrogate is { } high)
        {
            _pendingHighSurrogate = null;
            if (char.IsLowSurrogate(character))
            {
                Write(new Rune(high, character));
                return;
            }
            Write(new Rune(high));
        }
        if (char.IsHighSurrogate(character)) { _pendingHighSurrogate = character; return; }
        if (char.IsLowSurrogate(character)) { Write(new Rune(character)); return; }
        switch (character)
        {
            case '\x1b': _mode = TerminalVtParserMode.Escape; break;
            case '\u009b': BeginCsi(); break;
            case '\u009d': _mode = TerminalVtParserMode.Osc; break;
            case '\r': ClearWrap(); _cursorColumn = 0; break;
            case '\n': case '\v': case '\f':
                ClearWrap(); _cursorRow = _buffer.AdvanceLine(_cursorRow); break;
            case '\b': ClearWrap(); _cursorColumn = Math.Max(0, _cursorColumn - 1); break;
            case '\t':
                ClearWrap(); _cursorColumn = Math.Min(_columns - 1, ((_cursorColumn / 8) + 1) * 8); break;
            default: if (!char.IsControl(character)) Write(new Rune(character)); break;
        }
    }

    private void ConsumeEscape(char character)
    {
        switch (character)
        {
            case '[': BeginCsi(); break;
            case ']': _mode = TerminalVtParserMode.Osc; break;
            case '\x1b': break;
            default:
                _mode = character is >= '\x20' and <= '\x2f'
                    ? TerminalVtParserMode.EscapeIntermediate : TerminalVtParserMode.Text;
                break;
        }
    }

    private void BeginCsi()
    {
        _mode = TerminalVtParserMode.Csi;
        _controlBuffer = string.Empty;
    }

    private void ConsumeCsi(char character)
    {
        if (character is >= '\x40' and <= '\x7e')
        {
            ApplyCsi(character, _controlBuffer);
            _controlBuffer = string.Empty;
            _mode = TerminalVtParserMode.Text;
        }
        else if (_controlBuffer.Length < MaxControlBuffer) _controlBuffer += character;
    }

    private void ApplyCsi(char final, string parameters)
    {
        ClearWrap();
        var values = ParseParameters(parameters);
        var first = Parameter(values, 0, 1);
        switch (final)
        {
            case 'A': _cursorRow = Math.Max(0, _cursorRow - first); break;
            case 'B': _cursorRow = Math.Min(_rows - 1, _cursorRow + first); break;
            case 'C': _cursorColumn = Math.Min(_columns - 1, _cursorColumn + first); break;
            case 'D': _cursorColumn = Math.Max(0, _cursorColumn - first); break;
            case 'E': _cursorRow = Math.Min(_rows - 1, _cursorRow + first); _cursorColumn = 0; break;
            case 'F': _cursorRow = Math.Max(0, _cursorRow - first); _cursorColumn = 0; break;
            case 'G': _cursorColumn = Math.Clamp(first - 1, 0, _columns - 1); break;
            case 'H': case 'f':
                _cursorRow = Math.Clamp(Parameter(values, 0, 1) - 1, 0, _rows - 1);
                _cursorColumn = Math.Clamp(Parameter(values, 1, 1) - 1, 0, _columns - 1);
                break;
            case 'J': _buffer.EraseDisplay(_cursorRow, _cursorColumn, Parameter(values, 0, 0)); break;
            case 'K': _buffer.EraseLine(_cursorRow, _cursorColumn, Parameter(values, 0, 0)); break;
        }
    }

    private static int[] ParseParameters(string parameters)
    {
        var normalized = parameters.TrimStart('?', '>', '!', '=');
        return normalized.Length == 0 ? [] : normalized.Split(';')
            .Select(value => int.TryParse(value, out var parsed) && parsed >= 0 ? parsed : 0).ToArray();
    }

    private static int Parameter(int[] values, int index, int fallback) =>
        index >= values.Length || values[index] == 0 ? fallback : values[index];

    private void Write(Rune rune) => _buffer.Write(rune, ref _cursorRow, ref _cursorColumn, ref _wrapPending);
    private void ClearWrap() => _wrapPending = false;
}
