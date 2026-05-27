"""File tools: read, write, list. Paths resolve against the context cwd."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import Tool, ToolContext, ToolResult

MAX_READ_BYTES = 200_000


def _resolve(ctx: ToolContext, raw: str) -> Path:
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (ctx.cwd / p)


def _read_file(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
    path = _resolve(ctx, inp.get("path", ""))
    if not path.is_file():
        return ToolResult(f"No such file: {path}", is_error=True)
    data = path.read_bytes()
    truncated = len(data) > MAX_READ_BYTES
    text = data[:MAX_READ_BYTES].decode("utf-8", "replace")
    if truncated:
        text += f"\n\n[truncated; file is {len(data)} bytes]"
    return ToolResult(text)


def _write_file(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
    path = _resolve(ctx, inp.get("path", ""))
    content = inp.get("content", "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return ToolResult(f"Wrote {len(content)} chars to {path}")


def _list_files(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
    base = _resolve(ctx, inp.get("path", "."))
    if not base.exists():
        return ToolResult(f"No such path: {base}", is_error=True)
    if base.is_file():
        return ToolResult(str(base))
    depth = int(inp.get("depth", 1))
    lines: list[str] = []

    def walk(d: Path, level: int, prefix: str) -> None:
        if level > depth:
            return
        try:
            entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError as exc:
            lines.append(f"{prefix}[error: {exc}]")
            return
        for e in entries:
            if e.name.startswith(".") and e.name not in (".birkin",):
                continue
            mark = "/" if e.is_dir() else ""
            lines.append(f"{prefix}{e.name}{mark}")
            if e.is_dir():
                walk(e, level + 1, prefix + "  ")

    lines.append(f"{base}/")
    walk(base, 1, "  ")
    return ToolResult("\n".join(lines) if lines else "(empty)")


def tools() -> list[Tool]:
    return [
        Tool(
            name="read_file",
            description="Read a UTF-8 text file relative to the workspace. "
                        "Large files are truncated.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File path"}},
                "required": ["path"],
            },
            fn=_read_file,
        ),
        Tool(
            name="write_file",
            description="Create or overwrite a text file (parent dirs are "
                        "created automatically).",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            fn=_write_file,
        ),
        Tool(
            name="list_files",
            description="List files/directories under a path (default '.').",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "depth": {"type": "integer", "description": "Recursion depth (default 1)"},
                },
            },
            fn=_list_files,
        ),
    ]
