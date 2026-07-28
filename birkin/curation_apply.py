from __future__ import annotations

import json
from pathlib import Path

from . import mnemosyne
from .curation_contract import ANNOTATE_FIELDS, ANNOTATE_MAX_ITEMS
from .mnemosyne import Mnemosyne
from .skills import frontmatter


def _title_of(dex: Mnemosyne, s: str) -> str:
    e = dex.note_meta(s)
    return (e or {}).get("title", s)


def _append_related(vault: Path, dex: Mnemosyne, s: str, target_title: str) -> bool:
    e = dex.note_meta(s)
    if e is None:
        return False
    path = vault / e["rel"]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if f"[[{target_title}]]" in text:
        return False
    if "## Related" in text:
        new = text.rstrip() + f"\n- [[{target_title}]]\n"
    else:
        new = text.rstrip() + f"\n\n## Related\n- [[{target_title}]]\n"
    mnemosyne.atomic_write(path, new)
    dex.note_written(path)
    return True


def _append_line(vault: Path, dex: Mnemosyne, s: str, line: str) -> bool:
    e = dex.note_meta(s)
    if e is None:
        return False
    path = vault / e["rel"]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if line in text:
        return False
    mnemosyne.atomic_write(path, text.rstrip() + f"\n\n{line}\n")
    dex.note_written(path)
    return True


def _write_anchors(vault: Path, dex: Mnemosyne, s: str,
                   fields: dict[str, list[str]]) -> bool:
    """Merge retrieval anchors into a note's frontmatter. Body untouched.

    The body is not addressable by this code path at all — we split the
    frontmatter off, rewrite only whitelisted key lines, and re-attach the
    body bytes unchanged. That is the safety property `annotate` claims.
    """
    e = dex.note_meta(s)
    if e is None:
        return False
    path = vault / e["rel"]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
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
    mnemosyne.atomic_write(path, "---\n" + "\n".join(kept) + "\n---\n" + body)
    dex.note_written(path)
    return True


def apply_plan(accepted: list[dict], vault: Path,
               dex: Mnemosyne) -> list[dict]:
    effected: list[dict] = []
    for op in accepted:
        kind = op["op"]
        try:
            if kind == "rezone":
                dex.rezone(op["slug"], op["zone"])
                effected.append({"op": "rezone", "slug": op["slug"],
                                 "zone": op["zone"]})
            elif kind == "archive":
                dex.rezone(op["slug"], mnemosyne.ARCHIVE_ZONE)
                effected.append({"op": "archive", "slug": op["slug"]})
            elif kind == "link":
                a, b = op["a"], op["b"]
                ok1 = _append_related(vault, dex, a, _title_of(dex, b))
                ok2 = _append_related(vault, dex, b, _title_of(dex, a))
                if ok1 or ok2:
                    effected.append({"op": "link", "a": a, "b": b})
            elif kind == "annotate":
                fields = {k: op[k] for k in ANNOTATE_FIELDS if k in op}
                if fields and _write_anchors(vault, dex, op["slug"], fields):
                    effected.append({"op": "annotate", "slug": op["slug"],
                                     "fields": sorted(fields)})
            elif kind == "supersede":
                st, by = op["stale"], op["by"]
                ok = _append_line(vault, dex, st,
                                  f"> Superseded by [[{_title_of(dex, by)}]]")
                _append_related(vault, dex, by, _title_of(dex, st))
                if ok:
                    effected.append({"op": "supersede", "stale": st, "by": by})
        except (ValueError, OSError) as exc:
            effected.append({"op": kind, "error": str(exc)})
    return effected
