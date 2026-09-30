"""Mnemosyne — the mechanical memory engine (zones, index, decay, priority).

Named after the Greek goddess of memory. This is the LLM-free half of
birkin's memory palace (design: ``docs/mnemosyne-design.md``):

- **Index** — a stat-fingerprinted inverted index over the Obsidian vault, so
  ``search``/``render``/``list_notes`` never re-read the whole vault (closes
  the second half of review finding M4). Only changed files are re-parsed.
- **Zones** — notes live in one-level subdirectories of the vault
  (``vault/<zone>/note.md``, mempalace wing/room analog); the vault root is
  the *inbox*. ``_archive`` is the soft-forget zone (hermes curator's
  "archive, never delete").
- **BM25** — Okapi ranking over the index (k1/b as in mempalace's searcher),
  with a Unicode-aware tokenizer (NFKC + casefold, accent-folded words of any
  alphabet plus a truncation stem, Hangul/Han/kana runs with their unigrams
  and bigrams) and a small bonus for notes that match every script of a
  code-switched query. Limit: scripts whose words contain combining vowel
  signs (Devanagari, Thai) are split at those signs, because the stdlib
  ``re`` has no ``\\p{M}``.
- **Dynamics** — per-note Ebbinghaus decay + Hebbian potentiation adapted
  from mempalace ``dynamics.py`` and — unlike mempalace — wired into ranking.
- **Zone priority** — per-zone EMA of accesses with daily decay; boosts
  retrieval and orders the prompt digest.

Judgment (which notes are truly related, where a note belongs, what to
archive) stays with Morpheus/the LLM; this module only produces mechanical
candidates and applies decisions.

Two sidecar files live next to the notes:

- ``.birkin-index.json.z``  — CACHE (zlib JSON), rebuildable at any time.
- ``.birkin-dynamics.json`` — STATE (usage); survives index rebuilds.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import threading
import unicodedata
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .note_move import move_note_noreplace
from .skills import frontmatter

# -- constants (single tuning source; see design §8) -------------------------

K1, B = 0.9, 0.5                     # Okapi BM25 (mempalace searcher.py)
CAND = 32                             # BM25 candidates before re-ranking
STRENGTH_STEP, STRENGTH_CAP = 0.25, 5.0
STABILITY_INIT, STABILITY_GROWTH, STABILITY_CAP = 7.0, 1.5, 365.0
EFF_FLOOR = 0.05                      # nothing fully vanishes (mempalace)
SPACING_HOURS = 1.0                   # Cepeda spacing gate (mempalace)
ZONE_EMA_DECAY = 0.9                  # per-day zone priority decay
W_DYN, W_ZONE = 0.3, 0.2              # ranking boost weights
STALE_EFF, STALE_DAYS = 0.1, 90       # hermes curator archive tier
MAX_ZONES = 24
RELATED_LIMIT = 5                     # A-MEM: keep top-k small
RELATED_QUERY_TERMS = 12
INDEX_VERSION = 5                     # 5: Unicode tokenizer, stems, zlib file
SCRIPT_BONUS = 0.5                    # per extra query script a note matches
STEM_PREFIX, STEM_MIN, STEM_MARK = 5, 6, "~"   # truncation stem of long words

INDEX_FILE = ".birkin-index.json.z"
LEGACY_INDEX_FILE = ".birkin-index.json"   # pre-v5 cache, removed on save
DYNAMICS_FILE = ".birkin-dynamics.json"
ARCHIVE_ZONE = "_archive"
# identity is the always-rendered "L0" zone; it never counts as stale.
IDENTITY_ZONE = "identity"

ZONE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
_HAN_KANA = ("\u3005\u3007\u3040-\u309f\u30a1-\u30fa\u30fc-\u30ff\u31f0-\u31ff"
             "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0003134f")
# Syllables plus conjoining jamo; NFKC turns compatibility jamo into the latter.
_HANGUL = "\uac00-\ud7a3\u1100-\u11ff"
_HAN_KANA_CHAR = re.compile(f"[{_HAN_KANA}]")
_HANGUL_CHAR = re.compile(f"[{_HANGUL}]")
# one match per run: (Hangul/Han/kana run | any other letters/digits)
_RUN_RE = re.compile(rf"([{_HANGUL}{_HAN_KANA}]+)|([^\W_{_HANGUL}{_HAN_KANA}]+)")
# The English possessive clitic (Nana's -> nana), as search analyzers drop it.
# Left in, the lone "s" is a rare term that the query weight makes decisive.
_POSSESSIVE_RE = re.compile(r"(?<=\w)['\u2019]s\b")
# Every key _note_entry writes; a cached entry without one of them is re-parsed.
_ENTRY_KEYS = frozenset({
    "title", "rel", "zone", "type", "sources", "record_source", "trust",
    "shared_read_only", "tags", "links", "created", "updated", "confidence",
    "polarity", "expires_at", "valid_at", "invalid_at", "supersedes",
    "summary", "mtime", "size", "doclen", "terms"})

# Mechanical default placement for *new* notes (mempalace FOLDER_ROOM_MAP
# analog); Morpheus refines placement nightly via memory_rezone.
TYPE_ZONE = {
    "person": "people", "project": "projects", "preference": "identity",
    "fact": "knowledge", "topic": "knowledge", "session": "journal",
}


def slug(title: str) -> str:
    """Filesystem/wikilink slug (single source; memory.py re-exports)."""
    s = re.sub(r"[^\w\s-]", "", title.strip().lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s or "note"


def atomic_write(path: Path, text: str) -> None:
    """Write via temp sibling + os.replace so a crash can't truncate the file
    and a concurrent reader never sees a half-written one."""
    # The bytes on disk are exactly the UTF-8 encoding of `text` on every
    # platform (no "\n" -> "\r\n" rewrite on Windows), so digests taken over
    # the text match the file that was written.
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Binary form of :func:`atomic_write`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent),
                                    prefix=path.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


# -- pure functions -----------------------------------------------------------

def _fold_char(c: str) -> str:
    """Strip accents from Latin letters only (é -> e, ệ -> e); other scripts
    keep their marks (kana voicing marks, Cyrillic й)."""
    if ord(c) >= 0x250 and not "\u1e00" <= c <= "\u1eff":
        return c
    base = "".join(x for x in unicodedata.normalize("NFD", c)
                   if not unicodedata.combining(x))
    return base if len(base) == 1 else c


_HALFWIDTH_VOICING = frozenset("\uff9e\uff9f")


def normalize_with_offsets(text: str) -> tuple[str, list[int]]:
    """``text`` normalised exactly like :func:`tokenize` sees it (NFKC,
    casefold, Latin accent folding) plus, for every normalised character,
    the index of the original character it came from (and ``len(text)`` as
    a final sentinel), so a match found in the normalised text can be cut
    out of the original. Works per base character + the marks that compose
    with it (combining marks, halfwidth voicing marks, Hangul medial/final
    jamo)."""
    if text.isascii():
        return text.lower(), list(range(len(text) + 1))
    out: list[str] = []
    offsets: list[int] = []
    i, n = 0, len(text)
    while i < n:
        j = i + 1
        while j < n and (unicodedata.combining(text[j])
                         or text[j] in _HALFWIDTH_VOICING
                         or "\u1160" <= text[j] <= "\u11ff"):
            j += 1
        cluster = unicodedata.normalize("NFKC", text[i:j]).casefold()
        if not cluster.isascii():
            cluster = "".join(map(_fold_char, cluster))
        out.append(cluster)
        offsets.extend([i] * len(cluster))
        i = j
    offsets.append(n)
    return "".join(out), offsets


def tokenize(text: str) -> list[str]:
    """NFKC + casefold, then per run of one script class:

    - words of any alphabet -> one accent-folded token (``azafrán`` ->
      ``azafran``, ``Straße`` -> ``strasse``), plus for words of 6+ letters
      a truncation stem of their first 5 letters (``verlangerung`` ->
      ``verla~``) so inflections and compounds meet (``verlängert``);
    - Hangul/Han/kana runs -> the run, its unigrams and its bigrams, each
      once: the run preserves exact matching, the unigrams recover remembered
      characters, and the bigrams retain substring recall without an analyzer.

    A possessive ``'s`` is dropped before the runs are cut.
    """
    toks: list[str] = []
    norm = (text.lower() if text.isascii()
            else unicodedata.normalize("NFKC", text).casefold())
    if "'" in norm or "\u2019" in norm:
        norm = _POSSESSIVE_RE.sub("", norm)
    for run, word in _RUN_RE.findall(norm):
        if word:
            folded = word if word.isascii() else "".join(map(_fold_char, word))
            toks.append(folded)
            if len(folded) >= STEM_MIN and folded.isalpha():
                toks.append(folded[:STEM_PREFIX] + STEM_MARK)
        else:
            toks.extend(dict.fromkeys([run, *run,
                                       *(run[i:i + 2]
                                         for i in range(len(run) - 1))]))
    return toks


def _script(token: str) -> str:
    """Script class used by the code-switch bonus: "hangul", "cjk" (Han and
    kana together - one Japanese phrase mixes both), "latin" for every other
    letter, and "" for digit-only tokens, which belong to no language."""
    c = token[0]
    if _HANGUL_CHAR.match(c):
        return "hangul"
    if _HAN_KANA_CHAR.match(c):
        return "cjk"
    return "" if token.isdigit() else "latin"


def bm25_scores(terms: list[str], postings: dict[str, dict[str, int]],
                doclens: dict[str, int], avgdl: float,
                n_docs: int) -> dict[str, float]:
    """Okapi BM25 over an inverted index; returns {slug: score}.

    Query terms carry an idf^1 weight (ranking-v2 / ADR-043). A long natural
    question mixes one or two terms that identify the note with a dozen that
    appear everywhere; weighting the query side by idf lets the rare term
    decide the ranking instead of being outvoted by common ones.

    Queries that mix scripts get a coordination factor ``1 + SCRIPT_BONUS x
    (scripts matched - 1)``: in a code-switched query ("moving checklist
    手続き") the rare English words otherwise let English notes that match
    only them outrank the note that matches both halves. Single-script
    queries are unaffected.

    Truncation stems are ignored when a query that holds a Hangul, Han or
    kana term also holds more than one alphabetic word. There each long
    English word would score twice (word + stem) against English notes, and
    with the query weight above that lifts them over the note written in the
    other language. A lone alphabetic word in such a query is its anchor
    (a Korean question quoting one English term) and keeps its stem. Both
    halves were chosen on the dev split of the multilingual benchmark, see
    ``benchmarks/RESULTS.md``.
    """
    scores: dict[str, float] = {}
    scripts: dict[str, set[str]] = {}
    avgdl = avgdl or 1.0
    uniq = list(dict.fromkeys(terms))       # unique, order-preserving
    query_scripts = {_script(t) for t in uniq} - {""}
    if query_scripts & {"hangul", "cjk"} and sum(
            1 for t in uniq
            if _script(t) == "latin" and not t.endswith(STEM_MARK)) > 1:
        uniq = [t for t in uniq if not t.endswith(STEM_MARK)]
    for t in uniq:
        post = postings.get(t)
        if not post:
            continue
        df = len(post)
        idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
        qw = idf                            # query-side weight (idf^1)
        script = _script(t)
        for s, tf in post.items():
            dl = doclens.get(s, avgdl)
            denom = tf + K1 * (1 - B + B * dl / avgdl)
            scores[s] = scores.get(s, 0.0) + qw * idf * tf * (K1 + 1) / denom
            if script:
                scripts.setdefault(s, set()).add(script)
    if len(query_scripts) > 1:
        for s in scores:
            scores[s] *= 1 + SCRIPT_BONUS * max(0, len(scripts.get(s, ())) - 1)
    return scores


# Relative-time cues. Korean first: the benchmark's parser was English-only,
# so porting it verbatim would have shipped a feature birkin's primary user
# cannot trigger ("지난달에 정리한…" is exactly how the query gets typed).
_KO_UNIT_DAYS = {"일": 1, "주": 7, "개월": 30, "달": 30, "년": 365}
_KO_REL_RE = re.compile(r"(\d+)\s*(개월|일|주|달|년)\s*전")
_KO_WORD_CUES = {
    "그저께": 2, "그제": 2, "어제": 1, "엊그제": 2,
    "지난주": 7, "저번주": 7, "지난달": 30, "저번달": 30,
    "지난해": 365, "작년": 365,
}
_EN_REL_RE = re.compile(
    r"(\d+|a|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(day|week|month|year)s?\s+ago")
_EN_WORDS = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_EN_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}
TIME_PRIOR_LAMBDA = 0.3               # ranking-v2 sweep2/sweep3 frozen value


def temporal_target(query: str, now: datetime) -> tuple[datetime, float] | None:
    """``(target date, window sigma in days)`` for a relative-time cue.

    Returns None when the query carries no cue — which is the common case, so
    the prior costs nothing and changes nothing for ordinary searches.
    """
    q = (query or "").lower()

    def hit(days: int) -> tuple[datetime, float]:
        # Looser window the further back you point: "어제" is a day, "작년"
        # is not a day in particular.
        return now - timedelta(days=days), max(1.0, days * 0.15)

    m = _KO_REL_RE.search(q)
    if m:
        return hit(int(m.group(1)) * _KO_UNIT_DAYS[m.group(2)])
    for cue, days in _KO_WORD_CUES.items():
        if cue in q:
            return hit(days)
    m = _EN_REL_RE.search(q)
    if m:
        n = _EN_WORDS.get(m.group(1))
        if n is None and m.group(1).isdigit():
            n = int(m.group(1))
        if n:
            return hit(n * _EN_UNIT_DAYS[m.group(2)])
    if "yesterday" in q:
        return hit(1)
    if "last week" in q:
        return hit(7)
    if "last month" in q:
        return hit(30)
    return None


def time_prior(dt: datetime | None, target: datetime, sigma: float,
               lam: float = TIME_PRIOR_LAMBDA) -> float:
    """Gaussian recency multiplier; 1.0 (neutral) for an undated note."""
    if dt is None:
        return 1.0
    dist = abs((dt.date() - target.date()).days)
    return 1.0 + lam * math.exp(-(dist * dist) / (2 * sigma * sigma))


def _parse_dt(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def default_dynamics(created: str | None = None) -> dict[str, Any]:
    dt = _parse_dt(created) or datetime.now(timezone.utc)
    return {"strength": 1.0, "stability": STABILITY_INIT,
            "access_count": 0, "last_access": dt.isoformat()}


def effective_strength(dyn: dict[str, Any], now: datetime) -> float:
    """Ebbinghaus retention: ``strength · exp(−days/stability)``, floored.

    Unparseable ``last_access`` fails open (no decay) — a note must never
    become unreachable because of a corrupt timestamp.
    """
    strength = float(dyn.get("strength", 1.0))
    last = _parse_dt(dyn.get("last_access"))
    if last is None:
        return max(EFF_FLOOR, min(strength, STRENGTH_CAP))
    days = max(0.0, (now - last).total_seconds() / 86400.0)
    stability = max(1e-6, float(dyn.get("stability", STABILITY_INIT)))
    return max(EFF_FLOOR, strength * math.exp(-days / stability))


def potentiate(dyn: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Hebbian reinforcement on access; returns a NEW dict.

    Deviations from mempalace's +0.05/+0.1 additive constants are deliberate:
    those were tuned for edge co-occurrence, not note access. A personal
    vault sees few accesses, so strength moves in ~20 touches and stability
    grows multiplicatively (SM-2-style spaced repetition), gated on ≥1 h
    spacing (Cepeda effect) exactly like mempalace.
    """
    last = _parse_dt(dyn.get("last_access"))
    hours = ((now - last).total_seconds() / 3600.0) if last else SPACING_HOURS
    stability = float(dyn.get("stability", STABILITY_INIT))
    if hours >= SPACING_HOURS:
        stability = min(STABILITY_CAP, stability * STABILITY_GROWTH)
    return {
        "strength": min(STRENGTH_CAP,
                        float(dyn.get("strength", 1.0)) + STRENGTH_STEP),
        "stability": stability,
        "access_count": int(dyn.get("access_count", 0)) + 1,
        "last_access": now.isoformat(),
    }


def decayed_ema(ema: float, last_hit: str | None, today: date) -> float:
    """Zone EMA decayed lazily by ``0.9^days`` since it was last bumped."""
    if not last_hit:
        return float(ema)
    try:
        days = max(0, (today - date.fromisoformat(str(last_hit))).days)
    except ValueError:
        return float(ema)
    return float(ema) * (ZONE_EMA_DECAY ** days)


# -- note parsing -------------------------------------------------------------

def _note_entry(path: Path, rel: str) -> dict[str, Any] | None:
    """Parse one note file into an index entry (module-level for testability)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        st = path.stat()
    except OSError:
        return None
    meta, body = frontmatter.parse(text)
    title = str(meta.get("title") or path.stem)
    raw_tags = meta.get("tags")
    tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else []
    try:
        confidence = float(meta.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    # Retrieval anchors written by the curator's `annotate` op (aliases /
    # queries / xlang) are indexed like any other text — otherwise the op
    # would write frontmatter nothing ever reads. No INDEX_VERSION bump is
    # needed: annotating rewrites the file, so its stat fingerprint changes
    # and only that note is re-parsed.
    anchors: list[str] = []
    for key in ("aliases", "queries", "xlang"):
        raw = meta.get(key)
        if isinstance(raw, list):
            anchors.extend(str(v) for v in raw)
    terms: dict[str, int] = {}
    for tok in tokenize(" ".join([title, " ".join(tags), " ".join(anchors),
                                  body])):
        terms[tok] = terms.get(tok, 0) + 1
    rel = rel.replace("\\", "/")
    zone = rel.rsplit("/", 1)[0] if "/" in rel else ""
    summary = ""
    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            summary = line[:120]
            break
    raw_sources = meta.get("sources")
    sources = ([str(value) for value in raw_sources]
               if isinstance(raw_sources, list) else [])
    record_source = str(meta.get("record_source") or "") \
        or (sources[-1] if sources else "legacy")
    return {
        "title": title, "rel": rel, "zone": zone,
        "type": str(meta.get("type", "topic")),
        "sources": sources, "record_source": record_source,
        "trust": str(meta.get("trust") or ""),
        "shared_read_only": bool(meta.get("shared_read_only", False)),
        "tags": tags, "links": sorted(set(WIKILINK_RE.findall(text))),
        "created": str(meta.get("created", "")),
        "updated": str(meta.get("updated", "")),
        "confidence": confidence,
        "polarity": str(meta.get("polarity") or "positive"),
        "expires_at": (str(meta["expires_at"])
                       if meta.get("expires_at") else None),
        "valid_at": (str(meta["valid_at"])
                     if meta.get("valid_at") else None),
        "invalid_at": (str(meta["invalid_at"])
                       if meta.get("invalid_at") else None),
        "supersedes": ([str(value) for value in meta.get("supersedes", [])]
                       if isinstance(meta.get("supersedes"), list) else []),
        "summary": summary,
        "mtime": st.st_mtime, "size": st.st_size,
        "doclen": _doc_length(terms), "terms": terms,
    }


def _doc_length(terms: dict[str, int]) -> int:
    """BM25 document length. Truncation stems are left out: they repeat a
    word that is already counted, and letting them in changes the length
    normalisation of queries that never use a stem."""
    return sum(tf for t, tf in terms.items() if not t.endswith(STEM_MARK))


def _encode_index(notes: dict[str, dict[str, Any]]) -> bytes:
    """The index cache: compact UTF-8 JSON, DEFLATE-compressed (zlib level 1).
    ``surrogatepass`` keeps a note whose file name holds undecodable bytes
    from failing the flush."""
    raw = json.dumps({"version": INDEX_VERSION, "notes": notes},
                     separators=(",", ":"), ensure_ascii=False)
    return zlib.compress(raw.encode("utf-8", "surrogatepass"), 1)


def _valid_entry(entry: Any) -> bool:
    if not isinstance(entry, dict) or not _ENTRY_KEYS <= entry.keys():
        return False
    terms = entry.get("terms")
    return isinstance(terms, dict) and all(
        isinstance(tf, int) for tf in terms.values())


def _decode_index(blob: bytes) -> dict[str, dict[str, Any]]:
    """Entries of a current-version cache; malformed entries are left out so
    the next refresh re-parses their notes."""
    data = json.loads(zlib.decompress(blob).decode("utf-8", "surrogatepass"))
    if not isinstance(data, dict) or data.get("version") != INDEX_VERSION:
        return {}
    notes = data.get("notes")
    if not isinstance(notes, dict):
        return {}
    return {s: e for s, e in notes.items() if _valid_entry(e)}


def _entry_expired(entry: dict[str, Any], today: date) -> bool:
    raw = entry.get("expires_at")
    if not raw:
        return False
    try:
        return date.fromisoformat(str(raw)) < today
    except ValueError:
        return False


# -- engine -------------------------------------------------------------------

class Mnemosyne:
    """Index + dynamics over one vault directory. Thread-safe via one RLock.

    Sidecar persistence is best-effort: the index is a rebuildable cache and
    dynamics are advisory telemetry, so a failed flush must never break a
    memory read/write (it self-heals on the next refresh).
    """

    def __init__(self, vault: Path):
        self.vault = Path(vault)
        self._lock = threading.RLock()
        self._pinned = False
        self._notes: dict[str, dict[str, Any]] | None = None
        self._dyn: dict[str, Any] | None = None
        self._postings: dict[str, dict[str, int]] = {}
        self._avgdl = 0.0

    @classmethod
    def from_entries(
        cls,
        vault: Path,
        entries: dict[str, dict[str, Any]],
    ) -> Mnemosyne:
        dex = cls(vault)
        dex._notes = {
            slug: dict(entry)
            for slug, entry in entries.items()
        }
        for slug, entry in dex._notes.items():
            dex._add_postings(slug, entry.get("terms") or {})
        dex._recompute_avgdl()
        dex._pinned = True
        return dex

    # -- persistence --------------------------------------------------------

    @property
    def _index_path(self) -> Path:
        return self.vault / INDEX_FILE

    @property
    def _dyn_path(self) -> Path:
        return self.vault / DYNAMICS_FILE

    def _load(self) -> None:
        try:
            notes = _decode_index(self._index_path.read_bytes())
        except (OSError, ValueError, zlib.error):
            notes = {}   # missing, older or corrupt cache: refresh() rebuilds it
        self._notes = notes
        self._postings = {}
        for s, e in notes.items():
            self._add_postings(s, e.get("terms") or {})
        self._recompute_avgdl()

        self._load_dynamics()

    def _load_dynamics(self) -> None:
        dyn: dict[str, Any] = {"notes": {}, "zones": {}}
        try:
            raw = json.loads(self._dyn_path.read_text(encoding="utf-8"))
            if isinstance(raw.get("notes"), dict):
                dyn["notes"] = raw["notes"]
            if isinstance(raw.get("zones"), dict):
                dyn["zones"] = raw["zones"]
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
        self._dyn = dyn

    def _save_index(self) -> None:
        try:
            atomic_write_bytes(self._index_path,
                               _encode_index(self._notes or {}))
            (self.vault / LEGACY_INDEX_FILE).unlink(missing_ok=True)
        except OSError:
            pass   # cache flush is best-effort; rebuilt on next load

    def _save_dynamics(self) -> None:
        try:
            atomic_write(self._dyn_path,
                         json.dumps(self._dyn, separators=(",", ":")))
        except OSError:
            pass   # losing one access event beats failing the user's turn

    # -- postings maintenance ------------------------------------------------

    def _add_postings(self, s: str, terms: dict[str, int]) -> None:
        for t, tf in terms.items():
            self._postings.setdefault(t, {})[s] = tf

    def _drop_postings(self, s: str) -> None:
        entry = (self._notes or {}).get(s)
        for t in (entry or {}).get("terms", {}):
            post = self._postings.get(t)
            if post:
                post.pop(s, None)
                if not post:
                    del self._postings[t]

    def _recompute_avgdl(self) -> None:
        notes = self._notes or {}
        total = sum(e.get("doclen", 0) for e in notes.values())
        self._avgdl = (total / len(notes)) if notes else 0.0

    # -- scanning / refreshing ------------------------------------------------

    def _scan(self) -> dict[str, tuple[str, float, int]]:
        """slug -> (rel, mtime, size) for every .md at root + one zone level.

        Duplicate slugs across zones keep the newest file (shouldn't happen
        through birkin's own write path, but a user can hand-copy files)."""
        out: dict[str, tuple[str, float, int]] = {}

        def add(name: str, full: str, rel: str) -> None:
            if not name.endswith(".md"):
                return
            try:
                st = os.stat(full)
            except OSError:
                return
            s = name[:-3]
            cur = out.get(s)
            if cur is None or st.st_mtime > cur[1]:
                out[s] = (rel, st.st_mtime, st.st_size)

        try:
            top = list(os.scandir(self.vault))
        except OSError:
            return out
        for e in top:
            if e.name.startswith("."):
                continue
            if e.is_file():
                add(e.name, e.path, e.name)
            elif e.is_dir():
                try:
                    sub = list(os.scandir(e.path))
                except OSError:
                    continue
                for f in sub:
                    if f.is_file():
                        add(f.name, f.path, f"{e.name}/{f.name}")
        return out

    def refresh(self) -> None:
        """Bring the index up to date by stat fingerprints; re-parse only
        changed files. A stat pass is milliseconds at personal-vault scale
        and keeps externally edited notes (e.g. in Obsidian) visible
        immediately — the M4 win is *no re-parsing*, not no statting."""
        with self._lock:
            if self._pinned:
                return
            if self._notes is None:
                self._load()
            assert self._notes is not None
            scan = self._scan()
            changed = False
            for s in [s for s in self._notes if s not in scan]:
                self._drop_postings(s)
                del self._notes[s]
                changed = True
            for s, (rel, mtime, size) in scan.items():
                e = self._notes.get(s)
                if (e and e.get("rel") == rel and e.get("mtime") == mtime
                        and e.get("size") == size):
                    continue
                entry = _note_entry(self.vault / rel, rel)
                if entry is None:
                    continue
                if e:
                    self._drop_postings(s)
                self._notes[s] = entry
                self._add_postings(s, entry["terms"])
                changed = True
            if changed:
                self._recompute_avgdl()
                self._save_index()

    def rebuild(self) -> dict[str, int]:
        """Discard the cache, rescan everything, return stats."""
        with self._lock:
            if self._dyn is None:
                self._load_dynamics()   # skip parsing the index we discard
            self._notes = {}
            self._postings = {}
            self.refresh()
            return self.stats()

    def note_written(self, path: Path) -> None:
        """Targeted index update after birkin itself wrote one note file."""
        with self._lock:
            if self._notes is None:
                self._load()
            assert self._notes is not None
            try:
                rel = path.relative_to(self.vault).as_posix()
            except ValueError:
                return
            entry = _note_entry(path, rel)
            if entry is None:
                return
            s = path.stem
            if s in self._notes:
                self._drop_postings(s)
            self._notes[s] = entry
            self._add_postings(s, entry["terms"])
            self._recompute_avgdl()
            self._save_index()

    # -- accessors -------------------------------------------------------------

    def entries(self) -> dict[str, dict[str, Any]]:
        """A snapshot copy of all index entries. Callers iterate this while
        other threads may refresh/rezone, so never hand out the live dict
        (entry dicts themselves are replaced, not mutated, on update)."""
        with self._lock:
            self.refresh()
            return dict(self._notes or {})

    def note_meta(self, s: str) -> dict[str, Any] | None:
        with self._lock:
            self.refresh()
            e = (self._notes or {}).get(s)
            return dict(e) if e else None

    def resolve_rel(self, s: str) -> str | None:
        with self._lock:
            self.refresh()
            e = (self._notes or {}).get(s)
            return e["rel"] if e else None

    def dynamics_of(self, s: str) -> dict[str, Any]:
        with self._lock:
            if self._dyn is None:
                self._load()
            assert self._dyn is not None
            dyn = self._dyn["notes"].get(s)
            if dyn:
                return dict(dyn)
            e = (self._notes or {}).get(s) or {}
            return default_dynamics(e.get("created") or None)

    def set_dynamics(self, s: str, dyn: dict[str, Any]) -> None:
        """Overwrite one note's dynamics (maintenance/test seam)."""
        with self._lock:
            if self._dyn is None:
                self._load()
            assert self._dyn is not None
            self._dyn["notes"][s] = dict(dyn)
            self._save_dynamics()

    def effective_of(self, s: str, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        return effective_strength(self.dynamics_of(s), now)

    # -- dynamics recording ------------------------------------------------------

    def record_access(self, s: str, now: datetime | None = None) -> None:
        """Potentiate a note + bump its zone EMA. Unknown slugs are a no-op."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            if self._notes is None:
                self._load()
            assert self._notes is not None and self._dyn is not None
            e = self._notes.get(s)
            if e is None:
                self.refresh()
                e = self._notes.get(s)
                if e is None:
                    return
            self._dyn["notes"][s] = potentiate(self.dynamics_of(s), now)
            z = e["zone"]
            zs = self._dyn["zones"].get(z) or {}
            today = now.date()
            ema = decayed_ema(float(zs.get("ema", 0.0)),
                              zs.get("last_hit"), today) + 1.0
            self._dyn["zones"][z] = {"ema": ema,
                                     "last_hit": today.isoformat()}
            self._save_dynamics()

    def zone_priorities(self, today: date | None = None) -> dict[str, float]:
        """Normalized [0,1] priority per zone present in the vault."""
        # Default matches every caller (UTC-derived), so an argless call can't
        # silently diverge from the rest of the dynamics system.
        today = today or datetime.now(timezone.utc).date()
        with self._lock:
            if self._notes is None:
                self._load()
            assert self._notes is not None and self._dyn is not None
            zones = {e["zone"] for e in self._notes.values()}
            raw: dict[str, float] = {}
            for z in zones:
                zs = self._dyn["zones"].get(z) or {}
                raw[z] = decayed_ema(float(zs.get("ema", 0.0)),
                                     zs.get("last_hit"), today)
            mx = max(raw.values(), default=0.0)
            return {z: (v / mx if mx > 0 else 0.0) for z, v in raw.items()}

    # -- retrieval ------------------------------------------------------------

    def search(self, query: str, limit: int = 8, zone: str | None = None,
               include_archive: bool = False,
               now: datetime | None = None,
               valid_on: date | None = None) -> list[dict[str, Any]]:
        """BM25 × (1 + W_DYN·eff/cap + W_ZONE·zone priority), index-only."""
        self.refresh()
        now = now or datetime.now(timezone.utc)
        terms = tokenize(query)
        with self._lock:
            notes = self._notes or {}
            if not terms or not notes:
                return []
            doclens = {s: e.get("doclen", 0) for s, e in notes.items()}
            base = bm25_scores(terms, self._postings, doclens,
                               self._avgdl, len(notes))
            cands = sorted(base.items(), key=lambda kv: kv[1],
                           reverse=True)[:CAND]
            pri = self.zone_priorities(today=now.date())
            # "지난주에 정리한 …" — when the query names a time, notes from
            # around it get a gentle multiplier. No cue, no effect.
            when = temporal_target(query, now)
            # TTL is a user-facing calendar date -> LOCAL today, matching
            # memory._is_expired (render/list/purge) so no path disagrees.
            expiry_today = valid_on or date.today()
            hits: list[dict[str, Any]] = []
            for s, bm in cands:
                e = notes[s]
                if _entry_expired(e, expiry_today):
                    continue
                z = e["zone"]
                if zone is not None:
                    if z != zone:
                        continue
                elif z == ARCHIVE_ZONE and not include_archive:
                    continue
                eff = effective_strength(self.dynamics_of(s), now)
                score = bm * (1 + W_DYN * eff / STRENGTH_CAP
                              + W_ZONE * pri.get(z, 0.0))
                if when is not None:
                    score *= time_prior(
                        _parse_dt(e.get("updated")) or _parse_dt(e.get("created")),
                        when[0], when[1])
                hits.append({"slug": s, "title": e["title"], "zone": z,
                             "rel": e["rel"], "type": e["type"],
                             "summary": e["summary"], "links": e["links"],
                             "polarity": e["polarity"], "score": score,
                             "updated": e["updated"]})
            hits.sort(key=lambda h: (h["score"], h["updated"]), reverse=True)
            return hits[:limit]

    def related(self, s: str, limit: int = RELATED_LIMIT) -> list[dict[str, Any]]:
        """Mechanical link candidates for one note (A-MEM step 1): BM25 with
        the note's own top terms, excluding itself and already-linked notes.
        The LLM (Morpheus) judges which candidates become real links."""
        e = self.note_meta(s)
        if e is None:
            return []
        top_terms = [t for t, _ in sorted(((t, n) for t, n in e.get("terms", {}).items()
                                           if not t.endswith(STEM_MARK)),
                                          key=lambda kv: kv[1], reverse=True)
                     [:RELATED_QUERY_TERMS]]
        linked = {slug(t) for t in e.get("links", [])} | {s}
        hits = self.search(" ".join(top_terms), limit=limit + len(linked))
        return [h for h in hits if h["slug"] not in linked][:limit]

    def stale(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Notes past the archive tier (eff < STALE_EFF and unused >
        STALE_DAYS). ``identity`` never goes stale (it is the always-rendered
        L0 and render does not count as access); ``_archive`` already is."""
        now = now or datetime.now(timezone.utc)
        today = now.date()
        out: list[dict[str, Any]] = []
        for s, e in self.entries().items():
            if e["zone"] in (ARCHIVE_ZONE, IDENTITY_ZONE):
                continue
            if _entry_expired(e, today):
                continue
            dyn = self.dynamics_of(s)
            last = _parse_dt(dyn.get("last_access"))
            if last is None:
                continue
            days = (now - last).total_seconds() / 86400.0
            eff = effective_strength(dyn, now)
            if eff < STALE_EFF and days > STALE_DAYS:
                out.append({"slug": s, "title": e["title"], "zone": e["zone"],
                            "last_access": dyn.get("last_access", ""),
                            "eff": eff})
        out.sort(key=lambda x: x["last_access"])
        return out

    # -- placement ------------------------------------------------------------

    def rezone(self, s: str, zone: str) -> Path:
        """Move a note into another zone directory and update the index.

        ``zone`` may be a normal zone name, ``"_archive"``, or ``""``/
        ``"inbox"`` for the vault root. Raises ValueError on unknown notes,
        invalid names, or the zone cap."""
        z = "" if zone in ("", "inbox") else str(zone)
        if z and z != ARCHIVE_ZONE and not ZONE_RE.fullmatch(z):
            raise ValueError(f"invalid zone name {zone!r} "
                             "(want ^[a-z0-9][a-z0-9-]{{0,31}}$)")
        with self._lock:
            self.refresh()
            assert self._notes is not None
            e = self._notes.get(s)
            if e is None:
                raise ValueError(f"no note with slug {s!r}")
            existing = {en["zone"] for en in self._notes.values()
                        if en["zone"] and en["zone"] != ARCHIVE_ZONE}
            if (z and z != ARCHIVE_ZONE and z not in existing
                    and len(existing) >= MAX_ZONES):
                raise ValueError(f"zone cap reached ({MAX_ZONES}); "
                                 "re-use an existing zone")
            old = self.vault / e["rel"]
            new_dir = (self.vault / z) if z else self.vault
            new = new_dir / f"{s}.md"
            if old != new:
                new_dir.mkdir(parents=True, exist_ok=True)
                move_note_noreplace(old, new)
            rel = f"{z}/{s}.md" if z else f"{s}.md"
            try:
                st = new.stat()
                mtime, size = st.st_mtime, st.st_size
            except OSError:
                mtime, size = e["mtime"], e["size"]
            self._notes[s] = {**e, "rel": rel, "zone": z,
                              "mtime": mtime, "size": size}
            self._save_index()
            return new

    # -- stats ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        with self._lock:
            notes = self._notes or {}
            zones = {e["zone"] or "inbox" for e in notes.values()}
            return {"notes": len(notes), "zones": len(zones),
                    "terms": len(self._postings), "stale": len(self.stale())}
