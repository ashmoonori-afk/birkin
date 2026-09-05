"""Scoped, evidence-linked search over live Office artifacts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import cast

from ..mnemosyne import bm25_scores, tokenize
from .errors import DocumentError
from .service_types import ExtractionResult

SCOPES = frozenset({"current_work", "selected_folder", "allowed_connection"})
MAX_SOURCES = 100
MAX_RESULTS = 100


def search_sources(
    query: object,
    sources: object,
    *,
    extract: Callable[..., ExtractionResult],
    limit: object = 20,
) -> dict[str, object]:
    """Rank live extraction spans and keep their exact locator and revision."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if isinstance(sources, (str, bytes)) or not isinstance(sources, Sequence):
        raise TypeError("sources must be an array")
    if not 1 <= len(sources) <= MAX_SOURCES:
        raise ValueError(f"sources must contain between 1 and {MAX_SOURCES} items")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESULTS:
        raise ValueError(f"limit must be between 1 and {MAX_RESULTS}")

    documents: dict[str, dict[str, object]] = {}
    postings: dict[str, dict[str, int]] = {}
    doclens: dict[str, int] = {}
    excluded = 0
    for source_index, raw in enumerate(sources):
        if not isinstance(raw, Mapping):
            raise TypeError("each source must be an object")
        source = cast("Mapping[str, object]", raw)
        scope = source.get("scope")
        if scope not in SCOPES:
            raise ValueError(f"invalid search scope: {scope!r}")
        if source.get("access_granted") is not True:
            excluded += 1
            continue
        artifact = source.get("artifact")
        if not isinstance(artifact, Mapping):
            raise TypeError("source artifact must be an object")
        try:
            extracted = extract(cast("Mapping[str, object]", artifact))
        except (DocumentError, FileNotFoundError, OSError):
            excluded += 1
            continue
        version = source.get("version")
        current_version = source.get("current_version", version)
        if not isinstance(version, str) or not version:
            raise ValueError("source version must be a non-empty string")
        if not isinstance(current_version, str) or not current_version:
            raise ValueError("source current_version must be a non-empty string")
        label = source.get("label")
        if not isinstance(label, str) or not label:
            uri = artifact.get("uri")
            label = Path(uri).name if isinstance(uri, str) else f"source-{source_index + 1}"
        for span_index, span in enumerate(extracted["spans"]):
            doc_id = f"{source_index}:{span_index}"
            terms = tokenize(span["text"])
            if not terms:
                continue
            documents[doc_id] = {
                "file": label,
                "scope": scope,
                "version": version,
                "is_older_version": version != current_version,
                "source_sha256": span["source_sha256"],
                "source_locator": span["source_locator"],
                "snippet": span["text"][:500],
            }
            counts = Counter(terms)
            doclens[doc_id] = len(terms)
            for term, count in counts.items():
                postings.setdefault(term, {})[doc_id] = count

    scores = bm25_scores(
        tokenize(query), postings, doclens,
        sum(doclens.values()) / len(doclens) if doclens else 0.0,
        len(doclens),
    )
    ranked = sorted(scores, key=lambda item: (scores[item], item), reverse=True)[:limit]
    return {
        "query": query,
        "results": [{**documents[item], "score": round(scores[item], 6)} for item in ranked],
        "excluded_sources": excluded,
        "cache": "none",
    }
