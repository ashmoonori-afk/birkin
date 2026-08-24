"""Deterministic safety gate and dense-zone link expansion."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from . import mnemosyne
from .curation_contract import (
    ARCHIVE_CAP_FRACTION,
    ARCHIVE_CAP_MIN,
    OPS,
    PROTECT_TYPES,
    CurationNote,
    GateResult,
)
from .json_types import JsonObject
from .mnemosyne import Mnemosyne


def _str_field(raw: JsonObject, key: str) -> str | None:
    value = raw.get(key)
    return value if isinstance(value, str) else None


def _is_protected(note_slug: str, snap: dict[str, CurationNote]) -> bool:
    entry = snap.get(note_slug)
    if entry is None:
        return False
    if entry["polarity"] == "negative" or entry["type"] in PROTECT_TYPES:
        return True
    zone = entry["zone"]
    return bool(
        zone
        and zone != mnemosyne.ARCHIVE_ZONE
        and entry["links"]
    )


def validate_clamp(
    plan: JsonObject,
    dex: Mnemosyne,
    snap: dict[str, CurationNote],
    now: datetime | None = None,
) -> GateResult:
    """Validate plan operations and clamp archives to the safety cap."""
    observed_at = now or datetime.now(timezone.utc)
    result = GateResult()
    known = set(snap)
    active = [
        note_slug
        for note_slug, entry in snap.items()
        if entry["zone"] != mnemosyne.ARCHIVE_ZONE
    ]
    raw_archive_cap = (
        max(
            ARCHIVE_CAP_MIN,
            math.ceil(ARCHIVE_CAP_FRACTION * max(1, len(active))),
        )
        if active
        else 0
    )
    result.archive_cap = min(raw_archive_cap, max(0, len(active) - 1))

    archive_ops: list[JsonObject] = []
    raw_ops = plan.get("ops", [])
    operations = raw_ops if isinstance(raw_ops, list) else []
    for raw_value in operations:
        if not isinstance(raw_value, dict):
            result.drop({"op": "?"}, "not an object")
            continue
        raw = raw_value
        op = raw.get("op")
        if not isinstance(op, str) or op not in OPS:
            result.drop({"op": str(op)[:40]}, f"unknown op {op!r}"[:60])
            continue
        if op == "rezone":
            note_slug = _str_field(raw, "slug")
            zone = str(raw.get("zone", ""))
            if note_slug is None or note_slug not in known:
                result.drop(raw, "unknown slug")
            elif zone in ("", "inbox"):
                result.drop(raw, "rezone needs a real zone")
            elif zone.strip().lower().replace(" ", "") == mnemosyne.ARCHIVE_ZONE:
                result.drop(raw, "rezone_to_archive_rejected")
            elif not mnemosyne.ZONE_RE.fullmatch(zone):
                result.drop(raw, "invalid zone name")
            else:
                result.accepted.append(raw)
        elif op == "link":
            left = _str_field(raw, "a")
            right = _str_field(raw, "b")
            if (
                left is None
                or right is None
                or left not in known
                or right not in known
            ):
                result.drop(raw, "unknown slug")
            elif left == right:
                result.drop(raw, "self-link")
            else:
                result.accepted.append(raw)
        elif op == "supersede":
            stale = _str_field(raw, "stale")
            replacement = _str_field(raw, "by")
            if (
                stale is None
                or replacement is None
                or stale not in known
                or replacement not in known
            ):
                result.drop(raw, "unknown slug")
            elif stale == replacement:
                result.drop(raw, "self-supersede")
            else:
                result.accepted.append(raw)
        elif op == "archive":
            note_slug = _str_field(raw, "slug")
            if note_slug is None or note_slug not in known:
                result.drop(raw, "unknown slug")
            elif snap[note_slug]["zone"] == mnemosyne.ARCHIVE_ZONE:
                result.drop(raw, "already archived")
            elif _is_protected(note_slug, snap):
                result.drop(raw, "protected note")
            else:
                archive_ops.append(raw)

    if archive_ops:
        archive_ops.sort(
            key=lambda operation: dex.effective_of(
                _str_field(operation, "slug") or "",
                observed_at,
            )
        )
        result.accepted.extend(archive_ops[:result.archive_cap])
        for over in archive_ops[result.archive_cap:]:
            result.drop(over, f"archive_capped (>{result.archive_cap})")
    return result


def dense_zone_links(
    accepted: list[JsonObject],
    snap: dict[str, CurationNote],
) -> list[JsonObject]:
    touched_zones = {
        zone
        for operation in accepted
        if operation.get("op") == "rezone"
        if (zone := _str_field(operation, "zone")) is not None
    }
    if not touched_zones:
        return accepted
    excluded = {
        value
        for operation in accepted
        if operation.get("op") == "supersede"
        for field in ("stale", "by")
        if (value := _str_field(operation, field)) is not None
    }

    def linkable(note_slug: str) -> bool:
        entry = snap.get(note_slug)
        return bool(
            entry is not None
            and entry["zone"] != mnemosyne.ARCHIVE_ZONE
            and entry["polarity"] != "negative"
            and entry["type"] not in PROTECT_TYPES
            and note_slug not in excluded
        )

    final_zone = {
        note_slug: entry["zone"]
        for note_slug, entry in snap.items()
        if linkable(note_slug)
    }
    for operation in accepted:
        kind = operation.get("op")
        if kind == "rezone":
            note_slug = _str_field(operation, "slug")
            zone = _str_field(operation, "zone")
            if note_slug is not None and zone is not None and linkable(note_slug):
                final_zone[note_slug] = zone
        elif kind == "archive":
            note_slug = _str_field(operation, "slug")
            if note_slug is not None:
                final_zone[note_slug] = mnemosyne.ARCHIVE_ZONE

    pairs = {
        frozenset((left, right))
        for operation in accepted
        if operation.get("op") == "link"
        if (left := _str_field(operation, "a")) is not None
        if (right := _str_field(operation, "b")) is not None
    }
    expanded = list(accepted)
    for zone in sorted(touched_zones):
        if zone == mnemosyne.ARCHIVE_ZONE:
            continue
        slugs = sorted(
            note_slug
            for note_slug, final in final_zone.items()
            if final == zone
        )
        for index, left in enumerate(slugs):
            for right in slugs[index + 1:]:
                pair = frozenset((left, right))
                if pair in pairs:
                    continue
                expanded.append(
                    {
                        "op": "link",
                        "a": left,
                        "b": right,
                        "reason": f"dense zone link: {zone}",
                    }
                )
                pairs.add(pair)
    return expanded
