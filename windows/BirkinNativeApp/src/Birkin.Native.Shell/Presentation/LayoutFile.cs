using System.Text;
using System.Text.Json;

namespace Birkin.Native.Shell.Presentation;

public static class LayoutFile
{
    public static LayoutState Parse(string? json) =>
        TryParse(json, out var state, out _) ? state : LayoutState.Default;

    public static bool TryParse(string? json, out LayoutState state, out JsonException? error)
    {
        state = LayoutState.Default;
        error = null;
        if (string.IsNullOrWhiteSpace(json)) return true;

        try
        {
            using var document = JsonDocument.Parse(json);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object
                || !root.TryGetProperty("version", out var version)
                || version.ValueKind != JsonValueKind.Number
                || !version.TryGetInt32(out var number)
                || number != 1)
            {
                return true;
            }

            var defaults = LayoutState.Default;
            var navigation = ReadColumn(root, "navigation", defaults.Navigation,
                LayoutState.NavigationMinWidth, LayoutState.NavigationMaxWidth);
            var context = ReadColumn(root, "context", defaults.Context,
                LayoutState.ContextMinWidth, LayoutState.ContextMaxWidth);
            var touched = ReadString(root, "lastTouched") switch
            {
                "navigation" => LayoutPanel.Navigation,
                "context" => LayoutPanel.Context,
                _ => LayoutPanel.Context,
            };
            var focusRestore = ReadFocusRestore(root);
            var window = ReadWindow(root, defaults.Window);
            var hintShown = root.TryGetProperty("hints", out var hints)
                && hints.ValueKind == JsonValueKind.Object
                && hints.TryGetProperty("layoutTipShown", out var shown)
                && shown.ValueKind is JsonValueKind.True or JsonValueKind.False
                && shown.GetBoolean();
            state = new LayoutState(
                navigation,
                context,
                touched,
                focusRestore,
                window,
                new LayoutHintsState(hintShown));
            return true;
        }
        catch (JsonException exception)
        {
            error = exception;
            return false;
        }
    }

    public static string Serialize(LayoutState state)
    {
        using var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true }))
        {
            writer.WriteStartObject();
            writer.WriteNumber("version", 1);
            writer.WritePropertyName("columns");
            writer.WriteStartObject();
            WriteColumn(writer, "navigation", state.Navigation);
            WriteColumn(writer, "context", state.Context);
            writer.WriteEndObject();
            writer.WriteString("lastTouched", state.LastTouched == LayoutPanel.Navigation ? "navigation" : "context");
            writer.WritePropertyName("focusRestore");
            if (state.FocusRestore is null)
            {
                writer.WriteNullValue();
            }
            else
            {
                writer.WriteStartObject();
                writer.WriteBoolean("navigation", state.FocusRestore.Navigation);
                writer.WriteBoolean("context", state.FocusRestore.Context);
                writer.WriteEndObject();
            }
            writer.WritePropertyName("window");
            writer.WriteStartObject();
            writer.WriteNumber("width", state.Window.Width);
            writer.WriteNumber("height", state.Window.Height);
            if (state.Window.Left is { } left) writer.WriteNumber("left", left);
            if (state.Window.Top is { } top) writer.WriteNumber("top", top);
            writer.WriteString("state", state.Window.State == LayoutWindowMode.Maximized ? "Maximized" : "Normal");
            writer.WriteEndObject();
            writer.WritePropertyName("hints");
            writer.WriteStartObject();
            writer.WriteBoolean("layoutTipShown", state.Hints.LayoutTipShown);
            writer.WriteEndObject();
            writer.WriteEndObject();
        }
        return Encoding.UTF8.GetString(stream.ToArray());
    }

    private static LayoutColumnState ReadColumn(
        JsonElement root,
        string name,
        LayoutColumnState fallback,
        double minimum,
        double maximum)
    {
        if (!root.TryGetProperty("columns", out var columns)
            || columns.ValueKind != JsonValueKind.Object
            || !columns.TryGetProperty(name, out var column)
            || column.ValueKind != JsonValueKind.Object)
        {
            return fallback;
        }
        var width = fallback.Width;
        if (column.TryGetProperty("width", out var widthElement)
            && widthElement.ValueKind == JsonValueKind.Number
            && widthElement.TryGetDouble(out var parsed)
            && double.IsFinite(parsed)
            && parsed >= 0)
        {
            width = Math.Clamp(parsed, minimum, maximum);
        }
        var visible = column.TryGetProperty("visible", out var visibleElement)
            && visibleElement.ValueKind is JsonValueKind.True or JsonValueKind.False
                ? visibleElement.GetBoolean()
                : true;
        return new LayoutColumnState(width, visible);
    }

    private static LayoutFocusRestore? ReadFocusRestore(JsonElement root)
    {
        if (!root.TryGetProperty("focusRestore", out var focus)
            || focus.ValueKind == JsonValueKind.Null)
        {
            return null;
        }
        return focus.ValueKind == JsonValueKind.Object
            && focus.TryGetProperty("navigation", out var navigation)
            && navigation.ValueKind is JsonValueKind.True or JsonValueKind.False
            && focus.TryGetProperty("context", out var context)
            && context.ValueKind is JsonValueKind.True or JsonValueKind.False
                ? new LayoutFocusRestore(navigation.GetBoolean(), context.GetBoolean())
                : null;
    }

    private static LayoutWindowState ReadWindow(JsonElement root, LayoutWindowState fallback)
    {
        if (!root.TryGetProperty("window", out var window) || window.ValueKind != JsonValueKind.Object)
        {
            return fallback;
        }
        var width = ReadFiniteNumber(window, "width") is { } w
            ? Math.Clamp(w, LayoutState.WindowMinWidth, LayoutState.WindowMaxWidth)
            : fallback.Width;
        var height = ReadFiniteNumber(window, "height") is { } h
            ? Math.Clamp(h, LayoutState.WindowMinHeight, LayoutState.WindowMaxHeight)
            : fallback.Height;
        var left = ReadFiniteNumber(window, "left");
        var top = ReadFiniteNumber(window, "top");
        var state = ReadString(window, "state") == "Maximized"
            ? LayoutWindowMode.Maximized
            : LayoutWindowMode.Normal;
        return new LayoutWindowState(width, height, left, top, state);
    }

    private static double? ReadFiniteNumber(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value)
        && value.ValueKind == JsonValueKind.Number
        && value.TryGetDouble(out var number)
        && double.IsFinite(number)
            ? number
            : null;

    private static string? ReadString(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static void WriteColumn(Utf8JsonWriter writer, string name, LayoutColumnState column)
    {
        writer.WritePropertyName(name);
        writer.WriteStartObject();
        writer.WriteNumber("width", column.Width);
        writer.WriteBoolean("visible", column.Visible);
        writer.WriteEndObject();
    }
}
