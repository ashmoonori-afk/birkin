"""Optional, dependency-light signals layered over Mnemosyne's lexical ranker.

The module itself has no third-party imports.  The sentence-transformers
adapter imports its dependency only when selected, so core Birkin remains a
zero-dependency install.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Protocol, Sequence

from .mnemosyne import slug, tokenize


class EmbeddingBackend(Protocol):
    """Small local embedding seam used by production and deterministic tests."""

    name: str

    def embed(self, texts: list[str]) -> Sequence[Sequence[float]]: ...


class SentenceTransformerBackend:
    """Local sentence-transformers adapter, loaded only after explicit opt-in."""

    def __init__(self, model: str):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "semantic memory requires `pip install birkin[memory-semantic]`"
            ) from exc
        self.model = model
        self.name = f"sentence-transformers:{model}"
        self._encoder = SentenceTransformer(model)

    def embed(self, texts: list[str]) -> Sequence[Sequence[float]]:
        return self._encoder.encode(texts, normalize_embeddings=True).tolist()


def embedding_backend(name: str, model: str) -> EmbeddingBackend:
    if name == "sentence-transformers":
        return SentenceTransformerBackend(model)
    raise ValueError(f"unknown local memory embedding backend: {name!r}")


def cosine_scores(query: str, entries: dict[str, dict[str, Any]],
                  backend: EmbeddingBackend) -> dict[str, float]:
    """Embed one query and indexed note summaries, returning [0, 1] cosine."""
    slugs = list(entries)
    if not slugs:
        return {}
    texts = [query] + [entry_text(entries[item]) for item in slugs]
    vectors = list(backend.embed(texts))
    if len(vectors) != len(texts):
        raise ValueError("embedding backend returned the wrong vector count")
    query_vector = vectors[0]
    return {item: max(0.0, _cosine(query_vector, vectors[index + 1]))
            for index, item in enumerate(slugs)}


def entry_text(entry: dict[str, Any]) -> str:
    return " ".join((str(entry.get("title") or ""),
                     " ".join(map(str, entry.get("tags") or [])),
                     str(entry.get("summary") or "")))


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding vectors have inconsistent dimensions")
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    ln = math.sqrt(sum(float(value) ** 2 for value in left))
    rn = math.sqrt(sum(float(value) ** 2 for value in right))
    return dot / (ln * rn) if ln and rn else 0.0


def entity_scores(query: str, entries: dict[str, dict[str, Any]]) -> dict[str, float]:
    """Score local title/tag entities and one-hop ``[[wikilink]]`` edges."""
    query_terms = _entity_terms(query)
    if not query_terms:
        return {}
    direct: dict[str, float] = {}
    for item, entry in entries.items():
        terms = _entity_terms(" ".join((str(entry.get("title") or ""),
                                        " ".join(map(str, entry.get("tags") or [])))))
        overlap = len(query_terms & terms)
        direct[item] = overlap / len(query_terms) if overlap else 0.0
    scores = dict(direct)
    for item, score in direct.items():
        if score <= 0:
            continue
        for target in entries[item].get("links") or []:
            linked = slug(str(target))
            if linked in entries:
                scores[linked] = max(scores.get(linked, 0.0), score * 0.7)
    return scores


def _entity_terms(text: str) -> set[str]:
    # Mnemosyne's tokenizer preserves Hangul behavior; single-character ASCII
    # noise is dropped so articles do not become graph entities.
    return {term for term in tokenize(re.sub(r"[^\w가-힣]+", " ", text))
            if len(term) > 1}


def parse_day(raw: Any) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def validity_score(item: str, entry: dict[str, Any],
                   entries: dict[str, dict[str, Any]], as_of: date) -> float:
    """Return 1 current, 0 invalid, or 0.1 when superseded at ``as_of``."""
    start = parse_day(entry.get("valid_at"))
    end = parse_day(entry.get("invalid_at"))
    learned_wrong = parse_day(entry.get("expires_at"))
    if ((start and as_of < start) or (end and as_of >= end)
            or (learned_wrong and as_of >= learned_wrong)):
        return 0.0
    for successor in entries.values():
        supersedes = {slug(str(value)) for value in successor.get("supersedes") or []}
        successor_start = parse_day(successor.get("valid_at"))
        successor_end = parse_day(successor.get("invalid_at"))
        if (item in supersedes and (successor_start is None or successor_start <= as_of)
                and (successor_end is None or as_of <= successor_end)):
            return 0.1
    return 1.0


def overlaps(entry: dict[str, Any], since: date | None,
             until: date | None) -> bool:
    start = parse_day(entry.get("valid_at")) or date.min
    end = (parse_day(entry.get("invalid_at"))
           or parse_day(entry.get("expires_at")) or date.max)
    return not ((since and end < since) or (until and start > until))
