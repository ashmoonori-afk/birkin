"""Machine-consumed contract for Windows composer turn controls."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "windows" / "BirkinNativeApp"
VIEW = WINDOWS / "src" / "Birkin.Native.App" / "Views" / "ConversationView.xaml"
VIEW_CODE = VIEW.with_suffix(".xaml.cs")
STYLES = WINDOWS / "src" / "Birkin.Native.App" / "Styles" / "ShellStyles.xaml"
KEY_POLICY = (
    WINDOWS
    / "src"
    / "Birkin.Native.App"
    / "Views"
    / "WindowsSendKeyPolicy.cs"
)
COORDINATOR = (
    WINDOWS
    / "src"
    / "Birkin.Native.Shell"
    / "ShellCoordinator.OfficeWorkflow.cs"
)
COMMANDS = (
    WINDOWS
    / "src"
    / "Birkin.Native.Shell"
    / "Commands"
    / "ConversationCommands.cs"
)
AUTOMATION = "clr-namespace:System.Windows.Automation;assembly=PresentationCore"


def _element(automation_id: str) -> ElementTree.Element:
    root = ElementTree.parse(VIEW).getroot()
    attribute = f"{{{AUTOMATION}}}AutomationProperties.AutomationId"
    return next(
        element
        for element in root.iter()
        if element.attrib.get(attribute) == automation_id
    )


def test_stop_button_binds_canonical_interrupt_state_and_handler() -> None:
    stop = _element("conversation.stop")
    send = _element("conversation.send")
    actions = _element("conversation.actions")
    automation_id = f"{{{AUTOMATION}}}AutomationProperties.AutomationId"

    assert (
        stop.attrib["IsEnabled"]
        == "{Binding OfficeWorkflow.Availability.ConversationInterrupt.IsEnabled}"
    )
    assert stop.attrib["Click"] == "StopClicked"
    assert (
        stop.attrib[f"{{{AUTOMATION}}}AutomationProperties.Name"]
        == "응답 중지"
    )
    assert [child.attrib[automation_id] for child in actions] == [
        "conversation.stop",
        "conversation.send",
    ]
    assert stop.attrib["Style"] == "{StaticResource ComposerActionStyle}"
    assert send.attrib["Style"] == "{StaticResource ComposerActionStyle}"
    assert (
        send.attrib[f"{{{AUTOMATION}}}AutomationProperties.AcceleratorKey"]
        == "Ctrl+Enter"
    )
    styles = STYLES.read_text(encoding="utf-8")
    assert 'x:Key="ComposerActionStyle"' in styles
    assert '<Trigger Property="IsEnabled" Value="True">' in styles
    assert '<Trigger Property="IsKeyboardFocused" Value="True">' in styles
    assert "InterruptConversationAsync" in COORDINATOR.read_text(encoding="utf-8")
    assert '"chat.interrupt"' in COMMANDS.read_text(encoding="utf-8")


def test_ctrl_enter_is_guarded_by_wpf_composition_state() -> None:
    view_source = VIEW_CODE.read_text(encoding="utf-8")
    policy_source = KEY_POLICY.read_text(encoding="utf-8")

    assert "TextCompositionManager.AddPreviewTextInputStartHandler" in view_source
    assert "TextCompositionManager.AddPreviewTextInputUpdateHandler" in view_source
    assert "TextCompositionManager.AddPreviewTextInputHandler" in view_source
    assert "_hasMarkedText = true" in view_source
    assert "_hasMarkedText = false" in view_source
    assert 'LostKeyboardFocus="DraftKeyboardFocusLost"' in VIEW.read_text(
        encoding="utf-8"
    )
    assert 'PreviewKeyDown="DraftPreviewKeyDown"' in VIEW.read_text(encoding="utf-8")
    assert "await HandleDraftKeyAsync(" in view_source
    assert "Key.Enter" in policy_source
    assert "ModifierKeys.Control" in policy_source
    assert "!hasMarkedText" in policy_source
    assert "_restoreDraftFocus" in view_source
    assert "DraftBox.Focus()" in view_source
