using System.Text;
using Birkin.Native.Protocol.Framing;

namespace Birkin.Native.Protocol.Projection;

internal static partial class NativeProjectionReducer
{
    internal static NativeJsonObject NormalizeSnapshotBody(NativeJsonObject body)
    {
        var terminals = body["terminals"] as NativeJsonArray ?? throw BodyError();
        if (terminals.Values.Count == 0)
        {
            return Replace(body, ("terminals", terminals));
        }

        var normalized = terminals.Values.Select(value =>
            value is NativeJsonObject terminal ? NormalizeTerminal(terminal) : throw BodyError());
        return Replace(body, ("terminals", new NativeJsonArray(normalized)));
    }

    private static void ApplyTerminal(
        List<NativeJsonObject> terminals, string type, NativeJsonObject payload)
    {
        var terminalId = OptionalString(payload, "terminal_id");
        if (terminalId is null)
        {
            return;
        }
        var index = terminals.FindIndex(item => OptionalString(item, "terminal_id") == terminalId);
        if (type == "terminal.opened")
        {
            var terminal = new NativeJsonObject([
                new("terminal_id", new NativeJsonString(terminalId)),
                new("cwd", new NativeJsonString(OptionalString(payload, "cwd") ?? string.Empty)),
                new("screen", new NativeJsonString(string.Empty)),
                new("display", new NativeJsonString(string.Empty)),
                new("output_sequence", new NativeJsonInteger(0)),
                new("state", new NativeJsonString("running")),
                new("exit_status", NativeJsonNull.Value),
                new("columns", new NativeJsonInteger(80)),
                new("rows", new NativeJsonInteger(24)),
                new("read_only", new NativeJsonBoolean(true)),
            ]);
            if (index < 0)
            {
                terminals.Add(terminal);
            }
            else
            {
                terminals[index] = terminal;
            }
            return;
        }
        if (index < 0)
        {
            return;
        }

        var current = terminals[index];
        if (type == "terminal.output")
        {
            if (payload["sequence"] is not NativeJsonInteger sequence
                || current["output_sequence"] is not NativeJsonInteger currentSequence
                || sequence.Value != currentSequence.Value + 1)
            {
                return;
            }

            var screen = BoundNewest(
                (OptionalString(current, "screen") ?? string.Empty)
                + (OptionalString(payload, "data") ?? string.Empty));
            terminals[index] = NormalizeTerminal(Replace(current,
                ("screen", new NativeJsonString(screen)),
                ("output_sequence", sequence)));
            return;
        }

        terminals[index] = type switch
        {
            "terminal.resized" => NormalizeTerminal(Replace(current,
                ("columns", payload["columns"] ?? current["columns"]!),
                ("rows", payload["rows"] ?? current["rows"]!))),
            "terminal.exited" => NormalizeTerminal(Replace(current,
                ("state", new NativeJsonString("exited")),
                ("exit_status", payload["exit_status"] ?? NativeJsonNull.Value))),
            _ => current,
        };
    }

    private static NativeJsonObject NormalizeTerminal(NativeJsonObject terminal)
    {
        var screen = BoundNewest(OptionalString(terminal, "screen") ?? string.Empty);
        var pairs = new List<KeyValuePair<string, NativeJsonValue>>();
        var screenAdded = false;
        foreach (var pair in terminal.Pairs)
        {
            if (pair.Key is "lease" or "display" or "read_only")
            {
                continue;
            }
            if (pair.Key == "screen")
            {
                pairs.Add(new("screen", new NativeJsonString(screen)));
                pairs.Add(new("display", new NativeJsonString(RenderTerminalDisplay(terminal, screen))));
                screenAdded = true;
            }
            else
            {
                pairs.Add(pair);
            }
        }
        if (!screenAdded)
        {
            pairs.Add(new("screen", new NativeJsonString(screen)));
            pairs.Add(new("display", new NativeJsonString(RenderTerminalDisplay(terminal, screen))));
        }
        pairs.Add(new("read_only", new NativeJsonBoolean(true)));
        return new NativeJsonObject(pairs);
    }

    private static string RenderTerminalDisplay(NativeJsonObject terminal, string screen)
    {
        var columns = terminal["columns"] is NativeJsonInteger { Value: >= 1 } width
            ? checked((int)width.Value)
            : 80;
        var rows = terminal["rows"] is NativeJsonInteger { Value: >= 1 } height
            ? checked((int)height.Value)
            : 24;
        const string workspaceMarker = "[workspace]";
        const char workspacePadding = '\ue000';
        var cwd = OptionalString(terminal, "cwd");
        var safeScreen = screen;
        if (!string.IsNullOrEmpty(cwd))
        {
            var cwdCells = cwd.EnumerateRunes().Sum(TerminalCellWidth.Width);
            var padding = new string(workspacePadding, Math.Max(0, cwdCells - workspaceMarker.Length));
            safeScreen = screen.Replace(
                cwd,
                workspaceMarker + padding,
                StringComparison.OrdinalIgnoreCase);
        }
        var display = TerminalVtProjection.Render(safeScreen, columns, rows)
            .Replace(workspacePadding.ToString(), string.Empty, StringComparison.Ordinal);
        if (!string.IsNullOrEmpty(cwd))
        {
            display = display.Replace(cwd, workspaceMarker, StringComparison.OrdinalIgnoreCase);
            var promptGap = workspaceMarker + ">\n";
            var promptIndex = display.IndexOf(promptGap, StringComparison.Ordinal);
            while (promptIndex >= 0)
            {
                var contentIndex = promptIndex + promptGap.Length;
                while (contentIndex < display.Length && display[contentIndex] == ' ') contentIndex++;
                if (contentIndex < display.Length && display[contentIndex] != '\n')
                    display = display.Remove(promptIndex + workspaceMarker.Length + 1,
                        contentIndex - promptIndex - workspaceMarker.Length - 1);
                promptIndex = display.IndexOf(promptGap, promptIndex + workspaceMarker.Length,
                    StringComparison.Ordinal);
            }
        }
        var wideWrap = display.IndexOf('\n');
        while (wideWrap > 0 && wideWrap + 1 < display.Length)
        {
            var previous = new Rune(display[wideWrap - 1]);
            var next = new Rune(display[wideWrap + 1]);
            if (TerminalCellWidth.Width(previous) == 2
                && TerminalCellWidth.Width(next) == 2
                && screen.Contains(previous.ToString() + next, StringComparison.Ordinal))
            {
                display = display.Remove(wideWrap, 1);
            }
            else
            {
                wideWrap++;
            }
            wideWrap = display.IndexOf('\n', wideWrap);
        }
        return display;
    }

    private static string BoundNewest(string value) => value.Length <= TerminalVtProjection.DisplayBudget
        ? value
        : value[^TerminalVtProjection.DisplayBudget..];

}
