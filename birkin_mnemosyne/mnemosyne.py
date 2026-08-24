"""Mechanical memory engine compatibility surface.

Implementation is split by responsibility while this module preserves every
original constant, function, patchable parser, and class import path.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from .atomic import atomic_write as atomic_write
from .dynamics import (
    EFF_FLOOR as EFF_FLOOR,
    SPACING_HOURS as SPACING_HOURS,
    STABILITY_CAP as STABILITY_CAP,
    STABILITY_GROWTH as STABILITY_GROWTH,
    STABILITY_INIT as STABILITY_INIT,
    STRENGTH_CAP as STRENGTH_CAP,
    STRENGTH_STEP as STRENGTH_STEP,
    ZONE_EMA_DECAY as ZONE_EMA_DECAY,
    decayed_ema as decayed_ema,
    default_dynamics as default_dynamics,
    effective_strength as effective_strength,
    parse_datetime as _parse_datetime_impl,
    potentiate as potentiate,
)
from .engine import MemoryEngine as _MemoryEngine
from .index_config import (
    ARCHIVE_ZONE as ARCHIVE_ZONE,
    CAND as CAND,
    DYNAMICS_FILE as DYNAMICS_FILE,
    IDENTITY_ZONE as IDENTITY_ZONE,
    INDEX_FILE as INDEX_FILE,
    INDEX_VERSION as INDEX_VERSION,
    MAX_ZONES as MAX_ZONES,
    RELATED_LIMIT as RELATED_LIMIT,
    RELATED_QUERY_TERMS as RELATED_QUERY_TERMS,
    STALE_DAYS as STALE_DAYS,
    STALE_EFF as STALE_EFF,
    TYPE_ZONE as TYPE_ZONE,
    W_DYN as W_DYN,
    W_ZONE as W_ZONE,
    WIKILINK_RE as WIKILINK_RE,
    ZONE_RE as ZONE_RE,
)
from .index_entry import entry_expired as _entry_expired_impl
from .index_entry import note_entry as _note_entry_impl
from .index_types import NoteEntry
from .json_types import JsonValue
from .lexical import B as B
from .lexical import K1 as K1
from .lexical import bm25_scores as bm25_scores
from .lexical import slug as slug
from .lexical import tokenize as tokenize


_parse_dt: Callable[[JsonValue], datetime | None] = _parse_datetime_impl


def _note_entry(path: Path, rel: str) -> NoteEntry | None:
    """Parse one note through the original monkeypatch-compatible seam."""
    return _note_entry_impl(path, rel)


_entry_expired: Callable[[NoteEntry, date], bool] = _entry_expired_impl


def _public_note_entry(path: Path, rel: str) -> NoteEntry | None:
    return _note_entry(path, rel)


class Mnemosyne(_MemoryEngine):
    """Index, dynamics, retrieval, and zone placement for one vault."""

    _entry_parser: Callable[[Path, str], NoteEntry | None] = staticmethod(
        _public_note_entry
    )
