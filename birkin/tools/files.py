"""File tools: read, write, list. Paths resolve against the context cwd."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from . import Tool, ToolContext, ToolResult
from . import hashline

MAX_READ_BYTES = 200_000


def _resolve(ctx: ToolContext, raw: str) -> Path:
    p = Path(raw).expanduser()
    p = p if p.is_absolute() else (ctx.cwd / p)
    # Opt-in path jail (default off — see config "fs_jail"). When on, confine
    # file tools to the workspace and ~/.birkin so the native loop can't read or
    # overwrite arbitrary files via an absolute path or "..". Off by default to
    # preserve existing behavior (the project's choice is warn, not hard-deny).
    if ctx.cfg.get("fs_jail"):
        _enforce_jail(ctx, p)
    return p


def _jail_roots(ctx: ToolContext) -> list[Path]:
    roots = [Path(ctx.cwd).resolve()]
    try:
        from .. import config
        roots.append(config.birkin_home().resolve())
    except Exception:
        pass
    return roots


def _enforce_jail(ctx: ToolContext, p: Path) -> None:
    """Raise ValueError if ``p`` resolves outside the allowed roots.

    Uses realpath so a symlink can't redirect the write outside the jail."""
    rp = Path(os.path.realpath(p))
    for root in _jail_roots(ctx):
        if rp == root or root in rp.parents:
            return
    raise ValueError(
        f"fs_jail: refusing a path outside the workspace and ~/.birkin: {p}")


def _normalize_newlines(s: str) -> str:
    """CRLF/CR -> LF so hashline operates on clean ``\\n`` lines cross-platform."""
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _atomic_write_text(path: Path, text: str) -> None:
    """Write text via a temp sibling + os.replace so a crash can't truncate it.
    ``newline=""`` disables platform translation so LF stays LF (no CRLF surprise
    that would invalidate the hashes the agent just saw)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # mkstemp creates the temp file with O_EXCL + 0600 in the destination dir, so
    # a pre-planted symlink under a *predictable* name can't redirect the write.
    # (The old ``<file>.<pid>.tmp`` name was a TOCTOU foothold in shared dirs.)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent),
                                    prefix=path.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _read_file(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
    path = _resolve(ctx, inp.get("path", ""))
    if not path.is_file():
        return ToolResult(f"No such file: {path}", is_error=True)
    data = path.read_bytes()
    try:
        offset = max(0, int(inp.get("offset", 0) or 0))
    except (TypeError, ValueError):
        offset = 0
    if offset >= len(data) and len(data):
        return ToolResult(
            f"offset {offset} is past the end of the file ({len(data)} bytes).",
            is_error=True)
    if offset and inp.get("annotate"):
        # Annotation numbers lines from 1, so an offset read would hand
        # edit_file line numbers that point somewhere else in the file. The
        # hash anchor would reject the edit anyway — fail clearly instead.
        return ToolResult(
            "annotate cannot be combined with offset: line numbers would not "
            "match the file. Re-read from offset=0 to edit.", is_error=True)
    window = data[offset:offset + MAX_READ_BYTES]
    truncated = offset + len(window) < len(data)
    text = window.decode("utf-8", "replace")
    # annotate=true tags each line "{n}#{hash}| " so a later edit_file can be
    # hash-anchored (reject stale writes). See tools/hashline.py.
    if inp.get("annotate"):
        text = hashline.annotate(_normalize_newlines(text))
    if truncated:
        text += (f"\n\n[truncated at {offset + len(window)} of {len(data)} "
                 f"bytes; continue with offset={offset + len(window)}]")
    return ToolResult(text)


def _edit_file(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Apply hash-anchored line edits — only if each line still matches the hash
    the agent saw (read the file with annotate=true first). All-or-nothing."""
    path = _resolve(ctx, inp.get("path", ""))
    if not path.is_file():
        return ToolResult(f"No such file: {path}", is_error=True)
    edits = inp.get("edits") or []
    if not isinstance(edits, list) or not edits:
        return ToolResult("Provide a non-empty 'edits' list "
                          "({line, hash, new}).", is_error=True)
    original = _normalize_newlines(path.read_bytes().decode("utf-8", "replace"))
    new_text, errors = hashline.edit_text(original, edits)
    if errors:
        return ToolResult(
            "Edit rejected — file left UNCHANGED:\n- " + "\n- ".join(errors)
            + "\nRe-read the file with read_file annotate=true for fresh hashes.",
            is_error=True)
    _atomic_write_text(path, new_text)
    return ToolResult(f"Applied {len(edits)} edit(s) to {path}.")


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
                        "Large files are read in windows — pass offset to "
                        "continue past a truncation point. Set annotate=true to "
                        "tag each line '{n}#{hash}| ' for a later hash-anchored "
                        "edit_file (annotate cannot be used with offset).",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "offset": {"type": "integer", "description":
                               "Byte offset to start reading from (default 0)"},
                    "annotate": {"type": "boolean", "description":
                                 "Prefix lines with {n}#{hash}| for edit_file"},
                },
                "required": ["path"],
            },
            fn=_read_file,
        ),
        Tool(
            name="edit_file",
            description="Apply line edits that REJECT stale writes: each edit must "
                        "carry the line's current #hash (from read_file annotate=true). "
                        "All-or-nothing — if any hash is stale the file is untouched.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "edits": {
                        "type": "array",
                        "description": "Edits to apply",
                        "items": {
                            "type": "object",
                            "properties": {
                                "line": {"type": "integer", "description": "1-indexed line no."},
                                "hash": {"type": "string", "description": "the #hash you saw"},
                                "new": {"type": "string", "description": "replacement line text"},
                            },
                            "required": ["line", "hash", "new"],
                        },
                    },
                },
                "required": ["path", "edits"],
            },
            fn=_edit_file,
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
