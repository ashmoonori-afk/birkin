"""Load local or remote images into native multimodal tool results."""

from __future__ import annotations

import base64
import http.client
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Final

from ._types import (
    ImageContentBlock,
    ImageSource,
    TextContentBlock,
    Tool,
    ToolContent,
    ToolContext,
    ToolResult,
)
from .files import _resolve
from ..httpguard import pinned_opener
from .web import USER_AGENT

MAX_IMAGE_BYTES: Final = 5 * 1024 * 1024
_MEDIA_TYPES: Final = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
}


def _media_type(data: bytes) -> str | None:
    for signature, media_type in _MEDIA_TYPES.items():
        if data.startswith(signature):
            return media_type
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _download_image(source: str) -> bytes | ToolResult:
    parsed = urllib.parse.urlsplit(source)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return ToolResult("Image URL must use HTTPS.", is_error=True)
    request = urllib.request.Request(
        source,
        headers={"User-Agent": USER_AGENT, "Accept": "image/*"},
    )
    try:
        with pinned_opener().open(request, timeout=30) as response:
            data = response.read(MAX_IMAGE_BYTES + 1)
    except (
        OSError,
        ValueError,
        http.client.HTTPException,
        urllib.error.URLError,
    ) as exc:
        return ToolResult(f"Image fetch failed: {exc}", is_error=True)
    if len(data) > MAX_IMAGE_BYTES:
        return ToolResult("Image exceeds the 5 MB limit.", is_error=True)
    return data


def _read_image(source: str, ctx: ToolContext) -> bytes | ToolResult:
    if source.startswith(("http://", "https://")):
        downloaded = _download_image(source)
        if isinstance(downloaded, ToolResult):
            return downloaded
        data = downloaded
    else:
        path = _resolve(ctx, source.removeprefix("file://"))
        try:
            with path.open("rb") as image_file:
                data = image_file.read(MAX_IMAGE_BYTES + 1)
        except OSError as exc:
            return ToolResult(f"Image read failed: {exc}", is_error=True)
    if len(data) > MAX_IMAGE_BYTES:
        return ToolResult("Image exceeds the 5 MB limit.", is_error=True)
    return data


def _image_content(data: bytes, question: str, source: str) -> ToolContent:
    media_type = _media_type(data)
    if media_type is None:
        return "Only PNG, JPEG, GIF, and WebP images are supported."
    text: TextContentBlock = {
        "type": "text",
        "text": (
            f"Image loaded from {source}. Use built-in vision to answer."
            + (f"\nQuestion: {question.strip()}" if question.strip() else "")
        ),
    }
    image: ImageContentBlock = {
        "type": "image",
        "source": ImageSource(
            type="base64",
            media_type=media_type,
            data=base64.b64encode(data).decode("ascii"),
        ),
    }
    return [text, image]


def _vision_analyze(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
    source = str(inp.get("image_url", "")).strip()
    if not source:
        return ToolResult("Missing image_url", is_error=True)
    loaded = _read_image(source, ctx)
    if isinstance(loaded, ToolResult):
        return loaded
    content = _image_content(loaded, str(inp.get("question", "")), source)
    if isinstance(content, str):
        return ToolResult(content, is_error=True)
    return ToolResult(content)


def tools() -> list[Tool]:
    return [
        Tool(
            name="vision_analyze",
            description=(
                "Load a local or HTTP(S) image into context and inspect it "
                "with the active model's built-in vision."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "image_url": {"type": "string"},
                    "question": {"type": "string"},
                },
                "required": ["image_url", "question"],
            },
            fn=_vision_analyze,
        )
    ]
