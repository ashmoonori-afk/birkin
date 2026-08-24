from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TypedDict

from .json_types import JsonObject, JsonValue


PLAN_VERSION = 1
ARCHIVE_CAP_FRACTION = 0.20
ARCHIVE_CAP_MIN = 2
PROTECT_TYPES = {"identity", "preference"}
OPS = {"rezone", "link", "supersede", "archive"}

FORBIDDEN_PHRASE_TOKENS = ("ALL", "NOTES", "ARCHIVED", "SUCCESSFULLY")
_FORBIDDEN_RE = re.compile(r"\s*".join(FORBIDDEN_PHRASE_TOKENS),
                           re.IGNORECASE)
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"), None)


class CurationNote(TypedDict):
    """Snapshot fields used by the deterministic curation gate."""

    zone: str
    type: str
    polarity: str
    links: list[str]


class CatalogNote(CurationNote):
    """One note exposed to the mechanical curation catalog."""

    slug: str
    title: str
    summary: str
    related_candidates: list[str]


class StaleCandidate(TypedDict):
    """Minimal stale-note fields exposed to curation prompts."""

    slug: str
    title: str


class MechanicalCatalog(TypedDict):
    """Complete model-facing curation catalog."""

    notes: list[CatalogNote]
    existing_zones: list[str]
    stale_candidates: list[StaleCandidate]


@dataclass
class OpResult:
    op: JsonObject
    reason: str


@dataclass
class GateResult:
    accepted: list[JsonObject] = field(default_factory=list)
    dropped: list[OpResult] = field(default_factory=list)
    archive_cap: int = 0

    def drop(self, op: JsonObject, reason: str) -> None:
        self.dropped.append(OpResult(op, reason))


@dataclass
class CurationOutcome:
    provider: str
    model: str | None
    accepted: list[JsonObject]
    dropped: list[JsonObject]
    effected: list[JsonObject]
    archive_cap: int
    summary: str
    raw_text: str
    plan_ops: int


def sanitize_summary(summary: str) -> str:
    import unicodedata
    out = unicodedata.normalize("NFKC", summary or "").translate(_ZERO_WIDTH)
    return _FORBIDDEN_RE.sub("[redacted-canary]", out)


def sanitize_model_record(value: JsonValue) -> JsonValue:
    if isinstance(value, str):
        return sanitize_summary(value)
    if isinstance(value, list):
        return [sanitize_model_record(v) for v in value]
    if isinstance(value, dict):
        return {str(k): sanitize_model_record(v) for k, v in value.items()}
    return value


def sanitize_model_object(value: JsonObject) -> JsonObject:
    """Sanitize an object while preserving its typed dictionary shape."""
    return {key: sanitize_model_record(item) for key, item in value.items()}
