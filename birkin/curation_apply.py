from __future__ import annotations

from pathlib import Path

from . import mnemosyne
from .mnemosyne import Mnemosyne


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
