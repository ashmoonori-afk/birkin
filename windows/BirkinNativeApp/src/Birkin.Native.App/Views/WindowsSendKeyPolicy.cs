using System.Windows.Input;

namespace Birkin.Native.App.Views;

internal static class WindowsSendKeyPolicy
{
    public static bool ShouldSend(
        Key key,
        ModifierKeys modifiers,
        bool hasMarkedText) =>
        key == Key.Enter
        && modifiers == ModifierKeys.Control
        && !hasMarkedText;
}
