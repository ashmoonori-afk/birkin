"""Export a saved conversation as Markdown you own.

The vault already holds what birkin *learned*; the transcripts it learned from
sat in JSON that only birkin reads. Exporting them as Obsidian-shaped Markdown
finishes the same idea: your conversation history is a folder of files you can
grep, edit, link and keep after birkin is gone.

Deliberately one format. hermes exports Markdown/Quarto/HTML/prompt-only/HF —
none of those are the vault, so none of them are here.

Secrets are masked with the same masker as the transcript autosave; the export
is a copy of material that already passed it, and re-running is cheap
insurance against an older transcript written before a pattern was added.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import config, transcripts
from .mnemosyne import atomic_write, slug

EXPORT_ZONE = "journal"


def _text_of(content: Any) -> str:
    """Flatten one message's content to plain text.

    Messages are either a string or a list of typed blocks; tool_use and
    tool_result blocks are noted rather than dumped — a transcript is for
    reading, and a 30 KB tool payload is not.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            parts.append(str(block))
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(str(block.get("text", "")))
        elif kind == "tool_use":
            parts.append(f"*(tool: {block.get('name', '?')})*")
        elif kind == "tool_result":
            parts.append("*(tool result)*")
    return "\n\n".join(p for p in parts if p.strip())


def render(messages: list[dict[str, Any]], *, name: str,
           when: str | None = None) -> str:
    """One conversation as an Obsidian-shaped Markdown note."""
    when = when or date.today().isoformat()
    turns = [m for m in messages if isinstance(m, dict)]
    body: list[str] = [f"# {name}", ""]
    for msg in turns:
        text = _text_of(msg.get("content")).strip()
        if not text:
            continue
        who = "You" if msg.get("role") == "user" else "birkin"
        body.append(f"## {who}")
        body.append("")
        body.append(transcripts.redact_text(text))
        body.append("")
    fm = ("---\n"
          f"title: {name}\n"
          "type: session\n"
          f"created: {when}\n"
          f"updated: {date.today().isoformat()}\n"
          f"turns: {len(turns)}\n"
          "tags: [session, export]\n"
          "---\n\n")
    return fm + "\n".join(body).rstrip() + "\n"


def list_sessions(*, include_auto: bool = False) -> list[Path]:
    """Saved conversations, newest first."""
    files = sorted(config.sessions_dir().glob("*.json"), reverse=True)
    if include_auto:
        return files
    return [f for f in files if not transcripts.is_auto(f.stem)]


def export(stem: str, *, to_vault: bool = False,
           out_dir: Path | None = None) -> Path:
    """Write one saved session as Markdown; returns the path written.

    ``to_vault`` files it under the vault's journal zone, where the memory
    index will pick it up like any other note.
    """
    src = config.sessions_dir() / f"{stem}.json"
    if not src.is_file():
        raise FileNotFoundError(f"no session {stem!r}")
    messages = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(messages, list):
        raise ValueError(f"session {stem!r} is not a conversation")

    when = _stem_date(stem)
    text = render(messages, name=stem, when=when)
    if out_dir is not None:
        target_dir = Path(out_dir)
    elif to_vault:
        target_dir = config.vault_dir(config.load_config()) / EXPORT_ZONE
    else:
        target_dir = config.birkin_home() / "exports"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{when}-{slug(stem)}.md"
    atomic_write(path, text)
    return path


def _stem_date(stem: str) -> str:
    """Best-effort conversation date from the file stem, else today."""
    for chunk in stem.replace("__", "-").split("-"):
        if len(chunk) == 8 and chunk.isdigit():
            try:
                return datetime.strptime(chunk, "%Y%m%d").date().isoformat()
            except ValueError:
                continue
    return date.today().isoformat()
