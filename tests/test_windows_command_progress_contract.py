"""Machine-consumed contract for Windows command progress presentation."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

XAML = (
    Path(__file__).resolve().parents[1]
    / "windows"
    / "BirkinNativeApp"
    / "src"
    / "Birkin.Native.App"
    / "Views"
    / "ConversationView.xaml"
)
PRESENTATION = (
    "http://schemas.microsoft.com/winfx/2006/xaml/presentation"
)
AUTOMATION = (
    "clr-namespace:System.Windows.Automation;assembly=PresentationCore"
)


def _element(automation_id: str) -> ElementTree.Element:
    root = ElementTree.parse(XAML).getroot()
    attribute = f"{{{AUTOMATION}}}AutomationProperties.AutomationId"
    return next(
        element
        for element in root.iter()
        if element.attrib.get(attribute) == automation_id
    )


def test_command_progress_replaces_raw_enum_with_korean_presentation() -> None:
    source = XAML.read_text(encoding="utf-8")
    progress = _element("conversation.command-progress")
    label = _element("conversation.command-progress-label")

    assert "{Binding OfficeWorkflow.CommandState}" not in source
    assert (
        progress.attrib[f"{{{AUTOMATION}}}AutomationProperties.Name"]
        == "{Binding OfficeWorkflow.CommandProgressText}"
    )
    assert label.attrib["Text"] == "{Binding OfficeWorkflow.CommandProgressText}"


def test_command_progress_spinner_has_continuous_rotation() -> None:
    spinner = _element("conversation.command-progress-spinner")
    animations = spinner.findall(f".//{{{PRESENTATION}}}DoubleAnimation")

    assert spinner.attrib["Data"]
    assert spinner.attrib["Stroke"] == "{StaticResource AccentBrush}"
    assert len(animations) == 1
    assert animations[0].attrib == {
        "Storyboard.TargetProperty": (
            "(UIElement.RenderTransform).(RotateTransform.Angle)"
        ),
        "From": "0",
        "To": "360",
        "Duration": "0:0:0.8",
    }
    storyboard = spinner.find(f".//{{{PRESENTATION}}}Storyboard")
    assert storyboard is not None
    assert storyboard.attrib["RepeatBehavior"] == "Forever"
