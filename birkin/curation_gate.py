from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from . import mnemosyne
from .curation_contract import (
    ANNOTATE_FIELDS,
    ANNOTATE_MAX_CHARS,
    ANNOTATE_MAX_ITEMS,
    ARCHIVE_CAP_FRACTION,
    ARCHIVE_CAP_MIN,
    OPS,
    PROTECT_TYPES,
    GateResult,
    sanitize_summary,
)
from .mnemosyne import Mnemosyne


def _is_protected(dex: Mnemosyne, s: str, snap: dict[str, dict]) -> bool:
    e = snap.get(s)
    if e is None:
        return False
    if e.get("polarity") == "negative":
        return True
    if e.get("type") in PROTECT_TYPES:
        return True
    zone = e.get("zone") or ""
    if zone and zone != mnemosyne.ARCHIVE_ZONE and e.get("links"):
        return True
    return False


def validate_clamp(plan: dict[str, Any], dex: Mnemosyne,
                   snap: dict[str, dict],
                   now: datetime | None = None) -> GateResult:
    now = now or datetime.now(timezone.utc)
    res = GateResult()
    known = set(snap)
    active = [s for s, e in snap.items()
              if (e.get("zone") or "") != mnemosyne.ARCHIVE_ZONE]
    raw_archive_cap = (
        max(ARCHIVE_CAP_MIN,
            math.ceil(ARCHIVE_CAP_FRACTION * max(1, len(active))))
        if active else 0
    )
    res.archive_cap = min(raw_archive_cap, max(0, len(active) - 1))

    def _str_field(raw: dict[str, Any], key: str) -> str | None:
        v = raw.get(key)
        return v if isinstance(v, str) else None

    archive_ops: list[dict[str, Any]] = []
    for raw in plan.get("ops", []):
        if not isinstance(raw, dict):
            res.drop({"op": "?"}, "not an object")
            continue
        op = raw.get("op")
        if not isinstance(op, str) or op not in OPS:
            res.drop({"op": str(op)[:40]}, f"unknown op {op!r}"[:60])
            continue
        if op == "rezone":
            s, zone = _str_field(raw, "slug"), str(raw.get("zone", ""))
            if s is None or s not in known:
                res.drop(raw, "unknown slug")
            elif zone in ("", "inbox"):
                res.drop(raw, "rezone needs a real zone")
            elif zone.strip().lower().replace(" ", "") == mnemosyne.ARCHIVE_ZONE:
                res.drop(raw, "rezone_to_archive_rejected")
            elif not mnemosyne.ZONE_RE.fullmatch(zone):
                res.drop(raw, "invalid zone name")
            else:
                res.accepted.append(raw)
        elif op == "link":
            a, b = _str_field(raw, "a"), _str_field(raw, "b")
            if a is None or b is None or a not in known or b not in known:
                res.drop(raw, "unknown slug")
            elif a == b:
                res.drop(raw, "self-link")
            else:
                res.accepted.append(raw)
        elif op == "supersede":
            st, by = _str_field(raw, "stale"), _str_field(raw, "by")
            if st is None or by is None or st not in known or by not in known:
                res.drop(raw, "unknown slug")
            elif st == by:
                res.drop(raw, "self-supersede")
            else:
                res.accepted.append(raw)
        elif op == "annotate":
            s = _str_field(raw, "slug")
            if s is None or s not in known:
                res.drop(raw, "unknown slug")
                continue
            clean: dict[str, Any] = {"op": "annotate", "slug": s}
            for field_name in ANNOTATE_FIELDS:
                items = raw.get(field_name)
                if not isinstance(items, list):
                    continue
                kept = [sanitize_summary(v.strip())[:ANNOTATE_MAX_CHARS]
                        for v in items if isinstance(v, str) and v.strip()]
                if kept:
                    clean[field_name] = kept[:ANNOTATE_MAX_ITEMS]
            if len(clean) == 2:            # slug + op only: nothing to write
                res.drop(raw, "annotate has no usable field")
            else:
                res.accepted.append(clean)
        elif op == "archive":
            s = _str_field(raw, "slug")
            if s is None or s not in known:
                res.drop(raw, "unknown slug")
            elif (snap[s].get("zone") or "") == mnemosyne.ARCHIVE_ZONE:
                res.drop(raw, "already archived")
            elif _is_protected(dex, s, snap):
                res.drop(raw, "protected note")
            else:
                archive_ops.append(raw)

    if archive_ops:
        archive_ops.sort(key=lambda o: dex.effective_of(o["slug"], now))
        for keep in archive_ops[:res.archive_cap]:
            res.accepted.append(keep)
        for over in archive_ops[res.archive_cap:]:
            res.drop(over, f"archive_capped (>{res.archive_cap})")
    return res


def _dense_zone_links(accepted: list[dict[str, Any]],
                      snap: dict[str, dict]) -> list[dict[str, Any]]:
    touched_zones = {
        op["zone"] for op in accepted
        if op.get("op") == "rezone" and isinstance(op.get("zone"), str)
    }
    if not touched_zones:
        return accepted
    excluded = {
        str(op[field])
        for op in accepted
        if op.get("op") == "supersede"
        for field in ("stale", "by")
    }

    def _linkable(s: str) -> bool:
        e = snap.get(s)
        return (
            e is not None
            and str(e.get("zone") or "") != mnemosyne.ARCHIVE_ZONE
            and e.get("polarity") != "negative"
            and e.get("type") not in PROTECT_TYPES
            and s not in excluded
        )

    final_zone = {
        s: str(e.get("zone") or "")
        for s, e in snap.items()
        if _linkable(s)
    }
    for op in accepted:
        kind = op.get("op")
        if kind == "rezone":
            slug = str(op["slug"])
            if _linkable(slug):
                final_zone[slug] = str(op["zone"])
        elif kind == "archive":
            final_zone[str(op["slug"])] = mnemosyne.ARCHIVE_ZONE

    pairs = {
        frozenset((str(op["a"]), str(op["b"])))
        for op in accepted
        if op.get("op") == "link"
    }
    expanded = list(accepted)
    for zone in sorted(touched_zones):
        if zone == mnemosyne.ARCHIVE_ZONE:
            continue
        slugs = sorted(s for s, z in final_zone.items() if z == zone)
        for i, a in enumerate(slugs):
            for b in slugs[i + 1:]:
                pair = frozenset((a, b))
                if pair in pairs:
                    continue
                expanded.append({"op": "link", "a": a, "b": b,
                                 "reason": f"dense zone link: {zone}"})
                pairs.add(pair)
    return expanded
