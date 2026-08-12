from __future__ import annotations

import base64
import json
from pathlib import Path

from birkin.tools import ToolContext, build_registry


_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "/x8AAusB9Wl2nGQAAAAASUVORK5CYII="
)


def _context(tmp_path: Path, **cfg: bool) -> ToolContext:
    return ToolContext(cfg={"spill_threshold": 0, **cfg}, client=None, cwd=tmp_path)


def test_vision_analyze_attaches_local_image_when_file_is_valid(
        tmp_path: Path) -> None:
    # Given
    image = tmp_path / "pixel.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    registry = build_registry(_context(tmp_path), include={"vision"})

    # When
    result = registry.execute(
        "vision_analyze", {"image_url": str(image), "question": "What is shown?"}
    )

    # Then
    assert result.is_error is False
    assert isinstance(result.content, list)
    image_blocks = [
        block for block in result.content if block.get("type") == "image"
    ]
    assert len(image_blocks) == 1
    assert image_blocks[0]["source"]["media_type"] == "image/png"
    assert image_blocks[0]["source"]["data"] == base64.b64encode(
        _ONE_PIXEL_PNG
    ).decode("ascii")


def test_vision_analyze_rejects_private_url(tmp_path: Path) -> None:
    # Given
    registry = build_registry(_context(tmp_path), include={"vision"})

    # When
    result = registry.execute(
        "vision_analyze",
        {"image_url": "http://127.0.0.1/image.png", "question": "What is shown?"},
    )

    # Then
    assert result.is_error is True
    assert isinstance(result.content, str)


def test_vision_analyze_downloads_public_http_image(
        tmp_path: Path, monkeypatch) -> None:
    # Given
    from birkin.tools import vision

    class ImageResponse:
        status = 200

        @staticmethod
        def getheader(_name: str) -> None:
            return None

        @staticmethod
        def read(_limit: int) -> bytes:
            return _ONE_PIXEL_PNG

    class ImageConnection:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, *_args, **_kwargs) -> None:
            pass

        @staticmethod
        def getresponse() -> ImageResponse:
            return ImageResponse()

        def close(self) -> None:
            pass

    monkeypatch.setattr(vision, "_is_blocked_url", lambda _url: False)
    monkeypatch.setattr(vision.http.client, "HTTPConnection", ImageConnection)
    registry = build_registry(_context(tmp_path), include={"vision"})

    # When
    result = registry.execute(
        "vision_analyze",
        {"image_url": "http://example.com/pixel.png", "question": "What is shown?"},
    )

    # Then
    assert result.is_error is False
    assert isinstance(result.content, list)


def test_desktop_tools_require_explicit_opt_in(tmp_path: Path) -> None:
    # Given
    disabled = build_registry(_context(tmp_path))
    enabled = build_registry(_context(tmp_path, desktop_tools=True))

    # When
    disabled_names = disabled.names()
    enabled_names = enabled.names()

    # Then
    assert "desktop_windows" not in disabled_names
    assert "window_screenshot" not in disabled_names
    assert "desktop_windows" in enabled_names
    assert "window_screenshot" in enabled_names


def test_desktop_windows_returns_visible_window_state(
        tmp_path: Path, monkeypatch) -> None:
    # Given
    from birkin.tools import desktop

    monkeypatch.setattr(
        desktop,
        "_visible_windows",
        lambda: [
            desktop.DesktopWindow(
                handle=42,
                title="Birkin observation target",
                left=10,
                top=20,
                right=310,
                bottom=220,
                minimized=False,
            )
        ],
    )
    registry = build_registry(
        _context(tmp_path, desktop_tools=True), include={"desktop"}
    )

    # When
    result = registry.execute("desktop_windows", {"title": "observation"})

    # Then
    assert result.is_error is False
    assert isinstance(result.content, str)
    windows = json.loads(result.content)
    assert windows[0]["handle"] == 42
    assert windows[0]["width"] == 300
    assert windows[0]["height"] == 200


def test_window_screenshot_reports_disappeared_window(
        tmp_path: Path, monkeypatch) -> None:
    # Given
    from birkin.tools import desktop

    monkeypatch.setattr(desktop, "_visible_windows", lambda: [])
    registry = build_registry(
        _context(tmp_path, desktop_tools=True), include={"desktop"}
    )

    # When
    result = registry.execute("window_screenshot", {"title": "gone"})

    # Then
    assert result.is_error is True


def test_window_screenshot_attaches_pixels_from_matching_window(
        tmp_path: Path, monkeypatch) -> None:
    # Given
    from birkin.tools import desktop

    monkeypatch.setattr(
        desktop,
        "_visible_windows",
        lambda: [
            desktop.DesktopWindow(
                handle=42,
                title="Birkin observation target",
                left=10,
                top=20,
                right=12,
                bottom=22,
                minimized=False,
            )
        ],
    )
    monkeypatch.setattr(
        desktop, "_bounding_box_png", lambda _window: _ONE_PIXEL_PNG
    )
    monkeypatch.setattr(
        desktop, "_macos_window_png", lambda _window: _ONE_PIXEL_PNG
    )
    registry = build_registry(
        _context(tmp_path, desktop_tools=True), include={"desktop"}
    )

    # When
    result = registry.execute(
        "window_screenshot",
        {"handle": 42, "question": "Has the window changed?"},
    )

    # Then
    assert result.is_error is False
    assert isinstance(result.content, list)
    image_blocks = [
        block for block in result.content if block.get("type") == "image"
    ]
    assert len(image_blocks) == 1
    assert image_blocks[0]["source"]["media_type"] == "image/png"


def test_multimodal_event_text_excludes_image_bytes() -> None:
    # Given
    from birkin.agent import _visible_tool_content

    content = [
        {"type": "text", "text": "Ready"},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": "secret-pixel-bytes",
            },
        },
    ]

    # When
    visible = _visible_tool_content(content)

    # Then
    assert visible == "Ready"
    assert "secret-pixel-bytes" not in visible
