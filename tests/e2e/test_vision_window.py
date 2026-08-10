from __future__ import annotations

import sys
import tkinter
from pathlib import Path

import pytest

from birkin.tools import ToolContext, build_registry


@pytest.mark.skipif(sys.platform != "win32", reason="Windows desktop integration")
def test_visible_window_can_be_observed_through_real_os_surface(
        tmp_path: Path) -> None:
    # Given
    root = tkinter.Tk()
    root.title("Birkin vision e2e target")
    root.geometry("320x180+40+40")
    root.update_idletasks()
    root.update()
    registry = build_registry(
        ToolContext(
            cfg={"desktop_tools": True, "spill_threshold": 0},
            client=None,
            cwd=tmp_path,
        ),
        include={"desktop"},
    )

    try:
        # When
        windows = registry.execute("desktop_windows", {"title": "vision e2e"})
        screenshot = registry.execute(
            "window_screenshot",
            {"title": "vision e2e", "question": "Is the target visible?"},
        )

        # Then
        assert windows.is_error is False
        assert screenshot.is_error is False
        assert isinstance(screenshot.content, list)
        assert any(
            block.get("type") == "image" for block in screenshot.content
        )
    finally:
        root.destroy()
