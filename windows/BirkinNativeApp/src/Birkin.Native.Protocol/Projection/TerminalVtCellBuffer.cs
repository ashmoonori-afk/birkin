using System.Text;

namespace Birkin.Native.Protocol.Projection;

internal sealed record TerminalCell(string Text, bool IsContinuation)
{
    public static readonly TerminalCell Blank = new(" ", false);
    public static readonly TerminalCell Cleared = new(string.Empty, false);
}

internal sealed class TerminalCellLine
{
    public TerminalCellLine(IEnumerable<TerminalCell>? cells = null) => Cells = cells?.ToList() ?? [];
    public List<TerminalCell> Cells { get; }
    public TerminalCellLine Clone() => new(Cells);
    public string Render()
    {
        var rendered = new StringBuilder();
        for (var index = 0; index < Cells.Count; index++)
        {
            var cell = Cells[index];
            if (cell.IsContinuation) continue;
            if (cell != TerminalCell.Cleared)
            {
                rendered.Append(cell.Text);
                continue;
            }
            var previous = index > 0 ? Cells[index - 1] : null;
            var next = index + 1 < Cells.Count ? Cells[index + 1] : null;
            var betweenWide = previous is { IsContinuation: false }
                && next is { IsContinuation: false }
                && previous.Text.EnumerateRunes().Any(rune => TerminalCellWidth.Width(rune) == 2)
                && next.Text.EnumerateRunes().Any(rune => TerminalCellWidth.Width(rune) == 2);
            if (!betweenWide) rendered.Append(' ');
        }
        return rendered.ToString();
    }
}

internal sealed class TerminalVtCellBuffer
{
    private readonly List<TerminalCellLine> _lines;
    private readonly int _columns;
    private readonly int _rows;

    public TerminalVtCellBuffer(IEnumerable<TerminalCellLine> lines, int columns, int rows)
    {
        _columns = Math.Max(1, columns);
        _rows = Math.Max(1, rows);
        _lines = lines.Select(line => line.Clone()).ToList();
        Resize();
    }

    public TerminalCellLine[] CopyLines() => _lines.Select(line => line.Clone()).ToArray();

    public void Write(Rune rune, ref int row, ref int column, ref bool wrapPending)
    {
        var width = TerminalCellWidth.Width(rune);
        if (width == 0)
        {
            Attach(row, wrapPending ? column : column - 1, rune.ToString());
            return;
        }
        if (wrapPending || width == 2 && column == _columns - 1)
        {
            row = AdvanceLine(row);
            column = 0;
            wrapPending = false;
        }
        EnsureLine(row);
        var line = _lines[row].Cells;
        ClearPair(line, column);
        if (width == 2) ClearPair(line, column + 1);
        while (line.Count < column + width) line.Add(TerminalCell.Blank);
        line[column] = new TerminalCell(rune.ToString(), false);
        if (width == 2) line[column + 1] = new TerminalCell(string.Empty, true);
        if (column + width == _columns)
        {
            column = _columns - 1;
            wrapPending = true;
        }
        else
        {
            column += width;
        }
    }

    public int AdvanceLine(int row)
    {
        var next = row + 1;
        if (next < _rows)
        {
            EnsureLine(next);
            return next;
        }
        ScrollViewport();
        return _rows - 1;
    }

    public void EraseLine(int row, int column, int mode)
    {
        EnsureLine(row);
        var line = _lines[row].Cells;
        if (mode == 2)
        {
            line.Clear();
            return;
        }
        if (mode == 0)
        {
            if (column < line.Count)
            {
                ClearPair(line, column);
                line.RemoveRange(column, line.Count - column);
            }
            return;
        }
        for (var index = 0; index <= column && index < line.Count; index++) ClearPair(line, index);
    }

    public void EraseDisplay(int row, int column, int mode)
    {
        EnsureLine(row);
        if (mode == 0)
        {
            EraseLine(row, column, 0);
            for (var index = row + 1; index < _lines.Count; index++) _lines[index].Cells.Clear();
        }
        else if (mode == 1)
        {
            for (var index = 0; index < row; index++) _lines[index].Cells.Clear();
            EraseLine(row, column, 1);
        }
        else if (mode is 2 or 3)
        {
            foreach (var line in _lines) line.Cells.Clear();
        }
    }

    private void Attach(int row, int index, string value)
    {
        if (index < 0) return;
        EnsureLine(row);
        var line = _lines[row].Cells;
        if (line.Count == 0) return;
        index = Math.Min(index, line.Count - 1);
        if (line[index].IsContinuation) index--;
        if (index >= 0 && !line[index].IsContinuation)
            line[index] = line[index] with { Text = line[index].Text + value };
    }

    private static void ClearPair(List<TerminalCell> line, int index)
    {
        if (index < 0 || index >= line.Count) return;
        if (line[index].IsContinuation)
        {
            var overlapsContinuation = index > 0 && line[index - 1].IsContinuation;
            line[index] = TerminalCell.Cleared;
            if (index > 0 && !overlapsContinuation)
                line[index - 1] = TerminalCell.Cleared;
        }
        else
        {
            line[index] = TerminalCell.Cleared;
            if (index + 1 < line.Count && line[index + 1].IsContinuation)
                line[index + 1] = TerminalCell.Cleared;
        }
    }

    private void EnsureLine(int row)
    {
        while (_lines.Count <= row) _lines.Add(new TerminalCellLine());
    }

    private void ScrollViewport()
    {
        if (_lines.Count > 0) _lines.RemoveAt(0);
        EnsureLine(_rows - 1);
    }

    private void Resize()
    {
        while (_lines.Count > _rows) _lines.RemoveAt(0);
        foreach (var line in _lines)
        {
            if (line.Cells.Count <= _columns) continue;
            ClearPair(line.Cells, _columns - 1);
            line.Cells.RemoveRange(_columns, line.Cells.Count - _columns);
        }
    }
}
