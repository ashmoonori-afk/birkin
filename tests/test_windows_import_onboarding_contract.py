"""P1-7 portable contracts for Windows file intake and onboarding."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).parents[1]
APP = ROOT / "windows" / "BirkinNativeApp" / "src" / "Birkin.Native.App"
AUTOMATION = "clr-namespace:System.Windows.Automation;assembly=PresentationCore"
XAML = "http://schemas.microsoft.com/winfx/2006/xaml"


def _element(path: Path, automation_id: str) -> ElementTree.Element:
    root = ElementTree.parse(path).getroot()
    attribute = f"{{{AUTOMATION}}}AutomationProperties.AutomationId"
    return next(
        element
        for element in root.iter()
        if element.attrib.get(attribute) == automation_id
    )


def test_windows_picker_selects_supported_office_path_only() -> None:
    view = APP / "Views" / "ImportView.xaml"
    source = (APP / "Views" / "OfficeFilePicker.cs").read_text(encoding="utf-8")

    browse = _element(view, "import.browse")
    path = _element(view, "import.path")
    assert browse.attrib["Click"] == "BrowseClicked"
    assert path.attrib["IsReadOnly"] == "True"
    for extension in (".docx", ".xlsx"):
        assert extension in source
    for extension in (".pptx", ".pdf", ".hwpx", ".txt", "*.*"):
        assert extension not in source
    assert "OpenFileDialog" in source
    assert "Multiselect = false" in source
    assert "CheckFileExists = true" in source
    assert '"가져올 Excel 또는 Word 파일 선택"' in source


def test_full_window_drop_routes_one_supported_path_to_import() -> None:
    view = APP / "MainWindow.xaml"
    source = (APP / "MainWindow.xaml.cs").read_text(encoding="utf-8")
    snapshot = (
        APP / "Views" / "WorkspaceSnapshotView.xaml.cs"
    ).read_text(encoding="utf-8")
    office = (APP / "Views" / "OfficeView.xaml.cs").read_text(encoding="utf-8")
    import_panel = _element(
        APP / "Views" / "OfficeView.xaml",
        "office.import-panel",
    )

    overlay = _element(view, "import.drop-overlay")
    root = ElementTree.parse(view).getroot()
    assert root.attrib["AllowDrop"] == "True"
    assert root.attrib["PreviewDragEnter"] == "WindowDragEntered"
    assert root.attrib["PreviewDragOver"] == "WindowDragOver"
    assert root.attrib["PreviewDragLeave"] == "WindowDragLeft"
    assert root.attrib["PreviewDrop"] == "WindowDropped"
    assert overlay.attrib["IsHitTestVisible"] == "False"
    assert "DataFormats.FileDrop" in source
    assert "catch (COMException)" in source
    assert "OfficeFileSelection.Select" in source
    assert "ImportDroppedFilesAsync" in source
    assert "ImportDroppedFilesAsync" in snapshot
    assert import_panel.attrib[f"{{{XAML}}}Name"] == "ImportPanel"
    assert "ImportPanel.IsExpanded = true" in office


def test_imported_office_files_render_as_accessible_chips() -> None:
    view = APP / "Views" / "ImportView.xaml"
    source = view.read_text(encoding="utf-8")

    chips = _element(view, "import.chips")
    chip = _element(view, "import.chip")
    attribute = f"{{{AUTOMATION}}}AutomationProperties.Name"
    assert chips.attrib["ItemsSource"] == "{Binding OfficeWorkflow.Imports}"
    assert "WrapPanel" in source
    assert chip.attrib[attribute] == "{Binding AccessibleName}"


def test_import_refusal_is_inline_and_live() -> None:
    view = APP / "Views" / "ImportView.xaml"
    source = (APP / "Views" / "ImportView.xaml.cs").read_text(encoding="utf-8")
    refusal_source = (
        APP / "Views" / "OfficeFilePicker.cs"
    ).read_text(encoding="utf-8")
    status = _element(view, "import.status")
    attribute = f"{{{AUTOMATION}}}AutomationProperties.LiveSetting"

    assert status.attrib[attribute] == "Assertive"
    assert "ImportRefusalText.FromCode" in source
    assert "E_BODY" in refusal_source
    assert "E_STALE_CURSOR" in refusal_source
    assert "E_UNSUPPORTED_COMMAND" in refusal_source
    assert "_importPending" in source
    assert "Availability.FileImport.DisabledReason" in source


def test_file_intake_actions_and_chips_have_complete_visual_states() -> None:
    styles = (APP / "Styles" / "ShellStyles.xaml").read_text(encoding="utf-8")
    view = APP / "Views" / "ImportView.xaml"
    view_source = view.read_text(encoding="utf-8")

    assert 'x:Key="ActionButtonStyle"' in styles
    assert 'Property="IsEnabled" Value="False"' in styles
    assert 'Property="IsMouseOver" Value="True"' in styles
    assert 'Property="IsPressed" Value="True"' in styles
    assert 'Property="IsKeyboardFocused" Value="True"' in styles
    assert 'Property="MinHeight" Value="40"' in styles
    assert 'TextWrapping="Wrap"' in view_source
    assert 'MaxWidth="240"' in view_source
    actions = _element(view, "import.actions")
    assert actions.attrib["HorizontalAlignment"] == "Right"
    assert 'Background="#' not in (
        APP / "MainWindow.xaml"
    ).read_text(encoding="utf-8")
