using System.Windows;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class WorkspaceSnapshotView
{
    private void ToggleFocusClicked(object sender, RoutedEventArgs eventArgs) => ToggleFocusMode();

    private void ToggleFocusMode()
    {
        if (_compactMode)
        {
            ShowCompactPane(CompactPane.Primary);
            return;
        }
        _documentFocusRestore = null;
        if (_layout.FocusRestore is not null)
        {
            var restore = _layout.FocusRestore;
            _layout = _layout with
            {
                Navigation = _layout.Navigation with { Visible = restore.Navigation },
                Context = _layout.Context with { Visible = restore.Context },
                FocusRestore = null,
            };
        }
        else if (!_layout.Navigation.Visible && !_layout.Context.Visible)
        {
            _layout = _layout with
            {
                Navigation = _layout.Navigation with { Visible = true },
                Context = _layout.Context with { Visible = true },
            };
        }
        else
        {
            _layout = _layout with
            {
                FocusRestore = new LayoutFocusRestore(
                    _layout.Navigation.Visible, _layout.Context.Visible),
                Navigation = _layout.Navigation with { Visible = false },
                Context = _layout.Context with { Visible = false },
            };
        }
        ApplyLayout(true);
        _saveLayout?.Invoke(_layout, true);
    }
}
