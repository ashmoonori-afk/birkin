from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from . import mnemosyne
from .curation_contract import (
    ANNOTATE_FIELDS,
    ANNOTATE_MAX_ITEMS,
    CurationResidueError,
)
from .mnemosyne import Mnemosyne
from .skills import frontmatter

ReadNote = Callable[[str], tuple[Path, str] | None]
WriteNote = Callable[[str, str], Path]


def _title_of(dex: Mnemosyne, s: str) -> str:
    e = dex.note_meta(s)
    return (e or {}).get("title", s)


def _load_note(
    vault: Path,
    dex: Mnemosyne,
    slug: str,
    read_note: ReadNote | None,
) -> tuple[Path, str] | None:
    if read_note is not None:
        return read_note(slug)
    entry = dex.note_meta(slug)
    if entry is None:
        return None
    path = vault / entry["rel"]
    try:
        return path, path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None


def _store_note(
    path: Path,
    slug: str,
    text: str,
    dex: Mnemosyne,
    write_note: WriteNote | None,
) -> None:
    if write_note is not None:
        _ = write_note(slug, text)
        return
    mnemosyne.atomic_write(path, text)
    dex.note_written(path)


def _append_related(
    vault: Path,
    dex: Mnemosyne,
    s: str,
    target_title: str,
    read_note: ReadNote | None,
    write_note: WriteNote | None,
) -> bool:
    loaded = _load_note(vault, dex, s, read_note)
    if loaded is None:
        return False
    path, text = loaded
    if f"[[{target_title}]]" in text:
        return False
    if "## Related" in text:
        new = text.rstrip() + f"\n- [[{target_title}]]\n"
    else:
        new = text.rstrip() + f"\n\n## Related\n- [[{target_title}]]\n"
    _store_note(path, s, new, dex, write_note)
    return True


def _append_line(
    vault: Path,
    dex: Mnemosyne,
    s: str,
    line: str,
    read_note: ReadNote | None,
    write_note: WriteNote | None,
) -> bool:
    loaded = _load_note(vault, dex, s, read_note)
    if loaded is None:
        return False
    path, text = loaded
    if line in text:
        return False
    _store_note(
        path,
        s,
        text.rstrip() + f"\n\n{line}\n",
        dex,
        write_note,
    )
    return True


def _write_anchors(vault: Path, dex: Mnemosyne, s: str,
                   fields: dict[str, list[str]],
                   read_note: ReadNote | None,
                   write_note: WriteNote | None) -> bool:
    """Merge retrieval anchors into a note's frontmatter. Body untouched.

    The body is not addressable by this code path at all — we split the
    frontmatter off, rewrite only whitelisted key lines, and re-attach the
    body bytes unchanged. That is the safety property `annotate` claims.
    """
    loaded = _load_note(vault, dex, s, read_note)
    if loaded is None:
        return False
    path, text = loaded
    fm, body = frontmatter.split_frontmatter(text)
    if not fm.strip():
        return False                       # no frontmatter block to extend
    meta, _ = frontmatter.parse(text)

    merged: dict[str, list[str]] = {}
    changed = False
    for key, incoming in fields.items():
        old = meta.get(key)
        old_list = [str(v) for v in old] if isinstance(old, list) else []
        combined = list(dict.fromkeys(old_list + list(incoming)))
        combined = combined[:ANNOTATE_MAX_ITEMS]
        merged[key] = combined
        if combined != old_list:
            changed = True
    if not changed:
        return False

    kept = [ln for ln in fm.splitlines()
            if ln.split(":", 1)[0].strip() not in merged]
    for key, values in merged.items():
        rendered = ", ".join(json.dumps(v, ensure_ascii=False)
                             for v in values)
        kept.append(f"{key}: [{rendered}]")
    _store_note(
        path,
        s,
        "---\n" + "\n".join(kept) + "\n---\n" + body,
        dex,
        write_note,
    )
    return True


def apply_plan(accepted: list[dict], vault: Path,
               dex: Mnemosyne, *,
               move_note: Callable[[str, str], Path] | None = None,
               validate_vault: Callable[[], None] | None = None,
               read_note: ReadNote | None = None,
               write_note: WriteNote | None = None,
               ) -> list[dict]:
    effected: list[dict] = []
    if move_note is None:
        from .memory import VaultMemory
        move = VaultMemory({"vault_path": str(vault)}).rezone
    else:
        move = move_note
    for op in accepted:
        kind = op["op"]
        try:
            if validate_vault is not None:
                validate_vault()
            if kind == "rezone":
                move(op["slug"], op["zone"])
                dex.refresh()
                effected.append({"op": "rezone", "slug": op["slug"],
                                 "zone": op["zone"]})
            elif kind == "archive":
                move(op["slug"], mnemosyne.ARCHIVE_ZONE)
                dex.refresh()
                effected.append({"op": "archive", "slug": op["slug"]})
            elif kind == "link":
                a, b = op["a"], op["b"]
                ok1 = _append_related(
                    vault,
                    dex,
                    a,
                    _title_of(dex, b),
                    read_note,
                    write_note,
                )
                ok2 = _append_related(
                    vault,
                    dex,
                    b,
                    _title_of(dex, a),
                    read_note,
                    write_note,
                )
                if ok1 or ok2:
                    effected.append({"op": "link", "a": a, "b": b})
            elif kind == "annotate":
                fields = {k: op[k] for k in ANNOTATE_FIELDS if k in op}
                if fields and _write_anchors(
                    vault,
                    dex,
                    op["slug"],
                    fields,
                    read_note,
                    write_note,
                ):
                    effected.append({"op": "annotate", "slug": op["slug"],
                                     "fields": sorted(fields)})
            elif kind == "supersede":
                st, by = op["stale"], op["by"]
                ok = _append_line(
                    vault,
                    dex,
                    st,
                    f"> Superseded by [[{_title_of(dex, by)}]]",
                    read_note,
                    write_note,
                )
                _append_related(
                    vault,
                    dex,
                    by,
                    _title_of(dex, st),
                    read_note,
                    write_note,
                )
                if ok:
                    effected.append({"op": "supersede", "stale": st, "by": by})
        except OSError as exc:
            record = {"op": kind, "error": str(exc)}
            if isinstance(exc, CurationResidueError):
                record.update({
                    "residue": True,
                    "retryable": False,
                })
            effected.append(record)
        except ValueError as exc:
            effected.append({"op": kind, "error": str(exc)})
    return effected
