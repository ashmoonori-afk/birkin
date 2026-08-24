"""Tuning and storage constants for the mechanical memory index."""

from __future__ import annotations

import re
from typing import Final

CAND: Final = 32
W_DYN: Final = 0.3
W_ZONE: Final = 0.2
STALE_EFF: Final = 0.1
STALE_DAYS: Final = 90
MAX_ZONES: Final = 24
RELATED_LIMIT: Final = 5
RELATED_QUERY_TERMS: Final = 12
INDEX_VERSION: Final = 1

INDEX_FILE: Final = ".mnemosyne-index.json"
DYNAMICS_FILE: Final = ".mnemosyne-dynamics.json"
ARCHIVE_ZONE: Final = "_archive"
IDENTITY_ZONE: Final = "identity"

ZONE_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
WIKILINK_RE: Final[re.Pattern[str]] = re.compile(
    r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]"
)
TYPE_ZONE: Final[dict[str, str]] = {
    "person": "people",
    "project": "projects",
    "preference": "identity",
    "fact": "knowledge",
    "topic": "knowledge",
    "session": "journal",
}
