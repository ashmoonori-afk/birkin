"""Machine-consumed contract for Windows approval app notifications."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "windows" / "BirkinNativeApp"
TOAST = WINDOWS / "src" / "Birkin.Native.App" / "WindowsApprovalToast.cs"
ATTENTION = WINDOWS / "src" / "Birkin.Native.App" / "WindowsApprovalAttention.cs"
MAIN_WINDOW = WINDOWS / "src" / "Birkin.Native.App" / "MainWindow.xaml.cs"
PROJECT = WINDOWS / "src" / "Birkin.Native.App" / "Birkin.Native.App.csproj"


def test_windows_approval_toast_uses_official_app_notification_api() -> None:
    source = TOAST.read_text(encoding="utf-8")
    project = PROJECT.read_text(encoding="utf-8")

    assert "Microsoft.Windows.AppNotifications" in source
    assert "AppNotificationManager.Default" in source
    assert "AppNotificationBuilder" in source
    assert '<PackageReference Include="Microsoft.WindowsAppSDK"' in project


def test_windows_approval_toast_is_navigation_only() -> None:
    source = TOAST.read_text(encoding="utf-8")

    assert '.AddArgument("route", content.Route)' in source
    assert '.AddArgument("approval_id", content.ApprovalId)' in source
    assert ".AddButton(" not in source
    assert 'TryGetValue("route", out var route)' in source
    assert "_navigateToApprovals()" in source


def test_approval_signal_triggers_toast_and_taskbar_flash() -> None:
    attention = ATTENTION.read_text(encoding="utf-8")
    main_window = MAIN_WINDOW.read_text(encoding="utf-8")

    assert "_windowsAttention.Notify(signal)" in main_window
    assert "_toast?.Show(ApprovalToastContent.For(signal.ApprovalId))" in attention
    assert "_flasher.Start(" in attention
    assert "TaskbarItemProgressState.Paused" in attention
