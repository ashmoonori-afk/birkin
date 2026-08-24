"""Slugging, tokenization, and BM25 scoring for memory retrieval."""

from __future__ import annotations

import math
import re
from typing import Final

K1: Final = 1.5
B: Final = 0.75

_ASCII_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")
_HANGUL_RE: Final[re.Pattern[str]] = re.compile(r"[가-힣]+")


def slug(title: str) -> str:
    """Return the filesystem and wikilink slug for a title."""
    normalized = re.sub(r"[^\w\s-]", "", title.strip().lower())
    normalized = re.sub(r"[\s_-]+", "-", normalized).strip("-")
    return normalized or "note"


def tokenize(text: str) -> list[str]:
    """Return lowercase ASCII words, Hangul runs, and Hangul bigrams."""
    lowered = text.lower()
    tokens: list[str] = _ASCII_RE.findall(lowered)
    runs: list[str] = _HANGUL_RE.findall(lowered)
    for run in runs:
        tokens.append(run)
        if len(run) >= 2:
            tokens.extend(run[index:index + 2] for index in range(len(run) - 1))
    return tokens


def bm25_scores(
    terms: list[str],
    postings: dict[str, dict[str, int]],
    doclens: dict[str, int],
    avgdl: float,
    n_docs: int,
) -> dict[str, float]:
    """Score terms against all indexed documents using Okapi BM25.

    The five independent values are the established public scoring API: query,
    inverted index, document lengths, corpus average, and corpus size.
    """
    scores: dict[str, float] = {}
    normalized_avgdl = avgdl or 1.0
    for term in dict.fromkeys(terms):
        post = postings.get(term)
        if not post:
            continue
        document_frequency = len(post)
        inverse_frequency = math.log(
            1 + (n_docs - document_frequency + 0.5) / (document_frequency + 0.5)
        )
        for note_slug, frequency in post.items():
            document_length = doclens.get(note_slug, normalized_avgdl)
            denominator = frequency + K1 * (
                1 - B + B * document_length / normalized_avgdl
            )
            scores[note_slug] = scores.get(note_slug, 0.0) + (
                inverse_frequency * frequency * (K1 + 1) / denominator
            )
    return scores
