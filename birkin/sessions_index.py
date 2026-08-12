"""A rebuildable FTS5 index over the saved session transcripts.

``tools/sessions.py`` scored recall by counting substrings across the 400
newest files, re-reading and re-parsing every one of them per query. That
worked while the corpus was small; it does not rank, and it silently stops
seeing anything older than the cap.

This module keeps the JSON files as the source of truth and adds SQLite FTS5
purely as a **cache**: if the database is missing, stale, or corrupt, it is
rebuilt (or dropped and the caller falls back to the old scan). Nothing else in
birkin has to know it exists.

**Korean without a native tokenizer.** hermes ships a C extension that
re-emits CJK runs as overlapping character bigrams so FTS5 phrase matching
behaves like substring matching. The same trick works in pure Python at index
time: store a *shadow* copy of the text where every Hangul run is expanded into
its in-order bigrams, and expand the query identically. Two-character Korean
queries then match exactly, with no compiler, no ``.so``, and no dependency —
which also means it works on Windows, where the hermes build script does not.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import config

_ASCII_RE = re.compile(r"[a-z0-9]+")
# Hangul syllables/jamo, plus CJK ideographs and kana — everything that has no
# spaces between words and therefore defeats a whitespace tokenizer.
_CJK_RE = re.compile(r"[가-힣ᄀ-ᇿ぀-ヿ一-鿿]+")
_SCHEMA_VERSION = 2


def _path() -> Path:
    return config.birkin_home() / "sessions_index.db"


def _connect() -> sqlite3.Connection:
    # Short-lived connection per call, WAL — the ledger.py pattern.
    con = sqlite3.connect(_path(), timeout=5.0)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        version = con.execute("PRAGMA user_version").fetchone()[0]
        if version != _SCHEMA_VERSION:
            # This database is only a cache. Rebuilding is safer and simpler
            # than migrating FTS virtual tables in place.
            con.executescript(
                "DROP TABLE IF EXISTS session_fts;"
                "DROP TABLE IF EXISTS files;")
        con.executescript(
            "CREATE TABLE IF NOT EXISTS files ("
            "  stem TEXT PRIMARY KEY, mtime REAL, size INTEGER, date TEXT,"
            "  channel TEXT, model TEXT);"
            "CREATE VIRTUAL TABLE IF NOT EXISTS session_fts USING fts5("
            "  stem UNINDEXED, date UNINDEXED, channel UNINDEXED,"
            "  model UNINDEXED, raw UNINDEXED, body);"
            f"PRAGMA user_version = {_SCHEMA_VERSION};")
    except sqlite3.Error:
        # Close before propagating: Windows refuses to unlink a file whose
        # handle is still open, so leaving it open would make _reset() a no-op
        # and strand a corrupt cache forever.
        con.close()
        raise
    return con


# -- CJK bigram shadow text ------------------------------------------------

def bigram_shadow(text: str) -> str:
    """Expand every CJK run into its in-order overlapping bigrams.

    Order matters: the query side wraps the same bigrams in an FTS5 phrase, and
    a phrase only matches when the tokens are adjacent and in sequence. Emit
    them out of order and 2-character matching quietly degrades to an AND.
    """
    out: list[str] = []
    for run in _CJK_RE.findall(text.lower()):
        if len(run) == 1:
            out.append(run)
        else:
            out.extend(run[i:i + 2] for i in range(len(run) - 1))
    return " ".join(out)


def _index_body(text: str) -> str:
    """What actually goes in the FTS column: prose plus the shadow."""
    shadow = bigram_shadow(text)
    return f"{text}\n{shadow}" if shadow else text


def build_query(query: str) -> str:
    """Translate a user query into FTS5 syntax.

    ASCII terms are quoted literals; CJK terms become a quoted bigram phrase
    that matches the shadow text.
    """
    parts: list[str] = []
    low = query.lower()
    for term in _ASCII_RE.findall(low):
        parts.append(f'"{term}"')
    for run in _CJK_RE.findall(low):
        shadow = bigram_shadow(run)
        if shadow:
            parts.append(f'"{shadow}"')
    return " OR ".join(parts)


# -- index maintenance -----------------------------------------------------

def _read_session(path: Path) -> tuple[str, str, Optional[str]]:
    from .tools.sessions import _session_data
    return _session_data(path)


def refresh(con: sqlite3.Connection, progress_cb=None) -> int:
    """Sync the index with the transcript directory. Returns files reindexed.

    Change detection is a (mtime, size) fingerprint per file, the same
    incremental scheme Mnemosyne uses for the vault. There is no cap: the whole
    corpus is indexed, which is the point.
    """
    known = {row[0]: (row[1], row[2])
             for row in con.execute("SELECT stem, mtime, size FROM files")}
    seen: set[str] = set()
    touched = 0

    paths = list(config.sessions_dir().glob("*.json"))
    total = len(paths)
    for done, path in enumerate(paths, 1):
        try:
            try:
                st = path.stat()
            except OSError:
                continue
            stem = path.stem
            seen.add(stem)
            if known.get(stem) == (st.st_mtime, st.st_size):
                continue
            text, channel, model = _read_session(path)
            date = datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()
            con.execute("DELETE FROM session_fts WHERE stem = ?", (stem,))
            if text:
                con.execute(
                    "INSERT INTO session_fts "
                    "(stem, date, channel, model, raw, body) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (stem, date, channel, model, text, _index_body(text)))
            con.execute(
                "INSERT INTO files "
                "(stem, mtime, size, date, channel, model) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(stem) DO UPDATE SET "
                "mtime = excluded.mtime, size = excluded.size, "
                "date = excluded.date, channel = excluded.channel, "
                "model = excluded.model",
                (stem, st.st_mtime, st.st_size, date, channel, model))
            touched += 1
        finally:
            if progress_cb is not None:
                progress_cb(done, total)

    for stem in set(known) - seen:                  # transcript deleted/rotated
        con.execute("DELETE FROM session_fts WHERE stem = ?", (stem,))
        con.execute("DELETE FROM files WHERE stem = ?", (stem,))
        touched += 1

    con.commit()
    return touched


def _reset() -> None:
    """Throw the cache away; the next search rebuilds it from the JSON files."""
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(str(_path()) + suffix).unlink()
        except OSError:
            pass


# -- query -----------------------------------------------------------------

def search(query: str, limit: int = 5, *, since: Optional[str] = None,
           channel: Optional[str] = None,
           model: Optional[str] = None) -> Optional[list[dict[str, Any]]]:
    """BM25-ranked transcript search.

    Returns ``None`` when the index cannot serve the query, which is the
    caller's signal to fall back to the substring scan. Never raises: this is a
    cache, and a broken cache must not break recall.
    """
    fts_query = build_query(query)
    if not fts_query:
        return None
    try:
        con = _connect()
    except sqlite3.Error:
        _reset()
        return None

    rows: Optional[list[Any]] = None
    try:
        refresh(con)
        clauses = ["session_fts MATCH ?"]
        params: list[Any] = [fts_query]
        if since:
            clauses.append("date >= ?")
            params.append(since)
        if channel:
            clauses.append("lower(channel) = lower(?)")
            params.append(channel)
        if model:
            clauses.append("lower(model) = lower(?)")
            params.append(model)
        params.append(int(limit))
        rows = con.execute(
            "SELECT stem, date, channel, model, raw, "
            "bm25(session_fts) AS rank FROM session_fts WHERE "
            + " AND ".join(clauses) + " ORDER BY rank LIMIT ?", params
        ).fetchall()
    except sqlite3.Error:
        rows = None
    finally:
        con.close()

    if rows is None:
        _reset()          # only now that the handle is closed (see _connect)
        return None
    from .tools.sessions import _snippet
    terms = [term for term in query.lower().split() if term]
    return [{"session": stem, "date": date, "channel": channel,
             "model": model, "snippet": _snippet(raw, terms),
             "score": float(rank)}
            for stem, date, channel, model, raw, rank in rows]
