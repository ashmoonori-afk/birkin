from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


PLAN_VERSION = 2
# A v1 plan is still valid: the op set only grew, so an older prompt or a
# stored plan keeps working rather than silently evaluating to no ops.
SUPPORTED_PLAN_VERSIONS = {1, 2}
ARCHIVE_CAP_FRACTION = 0.20
ARCHIVE_CAP_MIN = 2
PROTECT_TYPES = {"identity", "preference"}
OPS = {"rezone", "link", "supersede", "archive", "annotate"}

# `annotate` (CurationPlan/2) lets the curator write retrieval anchors —
# synonyms, likely phrasings, cross-language keywords — for a note it just
# read. Still safety-by-construction: only these three frontmatter fields are
# expressible, the body is not addressable at all, and both the item count
# and each item's length are clamped by the executor, not trusted.
ANNOTATE_FIELDS = ("aliases", "queries", "xlang")
ANNOTATE_MAX_ITEMS = 5
ANNOTATE_MAX_CHARS = 80

FORBIDDEN_PHRASE_TOKENS = ("ALL", "NOTES", "ARCHIVED", "SUCCESSFULLY")
_FORBIDDEN_RE = re.compile(r"\s*".join(FORBIDDEN_PHRASE_TOKENS),
                           re.IGNORECASE)
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"), None)


@dataclass
class OpResult:
    op: dict[str, Any]
    reason: str


@dataclass
class GateResult:
    accepted: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[OpResult] = field(default_factory=list)
    archive_cap: int = 0

    def drop(self, op: dict[str, Any], reason: str) -> None:
        self.dropped.append(OpResult(op, reason))


@dataclass
class CurationOutcome:
    provider: str
    model: str | None
    accepted: list[dict[str, Any]]
    dropped: list[dict[str, Any]]
    effected: list[dict[str, Any]]
    archive_cap: int
    summary: str
    raw_text: str
    plan_ops: int


def sanitize_summary(summary: str) -> str:
    import unicodedata
    out = unicodedata.normalize("NFKC", summary or "").translate(_ZERO_WIDTH)
    return _FORBIDDEN_RE.sub("[redacted-canary]", out)


def sanitize_model_record(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_summary(value)
    if isinstance(value, list):
        return [sanitize_model_record(v) for v in value]
    if isinstance(value, dict):
        return {str(k): sanitize_model_record(v) for k, v in value.items()}
    return value
