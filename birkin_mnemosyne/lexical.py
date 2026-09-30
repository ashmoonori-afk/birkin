"""Slugging, tokenization, and BM25 scoring for memory retrieval."""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Final

K1: Final = 1.5
B: Final = 0.75
SCRIPT_BONUS: Final = 0.5
STEM_PREFIX: Final = 5
STEM_MIN: Final = 6
STEM_MARK: Final = "~"

_CJK: Final = (
    "\u3005\u3007\u3040-\u309f\u30a1-\u30fa\u30fc-\u30ff\u31f0-\u31ff"
    "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0003134f"
)
_HANGUL: Final = "\uac00-\ud7a3"
_CJK_CHAR: Final[re.Pattern[str]] = re.compile(f"[{_CJK}]")
# One match per run: (Han/kana run | Hangul run | any other letters/digits).
_RUN_RE: Final[re.Pattern[str]] = re.compile(
    rf"([{_CJK}]+)|([{_HANGUL}]+)|([^\W_{_CJK}{_HANGUL}]+)"
)
_HALFWIDTH_VOICING: Final = frozenset("\uff9e\uff9f")


def slug(title: str) -> str:
    """Return the filesystem and wikilink slug for a title."""
    normalized = re.sub(r"[^\w\s-]", "", title.strip().lower())
    normalized = re.sub(r"[\s_-]+", "-", normalized).strip("-")
    return normalized or "note"


def _fold_char(character: str) -> str:
    """Strip accents from Latin letters only; other scripts keep their marks."""
    if ord(character) >= 0x250 and not "\u1e00" <= character <= "\u1eff":
        return character
    base = "".join(
        part
        for part in unicodedata.normalize("NFD", character)
        if not unicodedata.combining(part)
    )
    return base if len(base) == 1 else character


def normalize_with_offsets(text: str) -> tuple[str, list[int]]:
    """Normalize text as ``tokenize`` sees it and map it back to the original.

    The second value holds, for every normalized character, the index of the
    original character it came from, plus ``len(text)`` as a final sentinel.
    Clusters are one base character and the marks that compose with it.
    """
    if text.isascii():
        return text.lower(), list(range(len(text) + 1))
    normalized: list[str] = []
    offsets: list[int] = []
    index, length = 0, len(text)
    while index < length:
        end = index + 1
        while end < length and (
            unicodedata.combining(text[end])
            or text[end] in _HALFWIDTH_VOICING
            or "\u1160" <= text[end] <= "\u11ff"
        ):
            end += 1
        cluster = unicodedata.normalize("NFKC", text[index:end]).casefold()
        if not cluster.isascii():
            cluster = "".join(map(_fold_char, cluster))
        normalized.append(cluster)
        offsets.extend([index] * len(cluster))
        index = end
    offsets.append(length)
    return "".join(normalized), offsets


def tokenize(text: str) -> list[str]:
    """Return accent-folded words with stems, Hangul runs, and CJK n-grams.

    Text is NFKC-normalized and casefolded. Words of any alphabet become one
    accent-folded token plus, from six letters, a five-letter truncation stem.
    Hangul runs add their bigrams; Han/kana runs become unigrams and bigrams.
    """
    tokens: list[str] = []
    normalized = unicodedata.normalize("NFKC", text).casefold()
    for cjk, hangul, word in _RUN_RE.findall(normalized):
        if word:
            folded = word if word.isascii() else "".join(map(_fold_char, word))
            tokens.append(folded)
            if len(folded) >= STEM_MIN and folded.isalpha():
                tokens.append(folded[:STEM_PREFIX] + STEM_MARK)
        elif hangul:
            tokens.append(hangul)
            tokens.extend(hangul[index:index + 2] for index in range(len(hangul) - 1))
        else:
            tokens.extend(cjk)
            tokens.extend(cjk[index:index + 2] for index in range(len(cjk) - 1))
    return tokens


def script(token: str) -> str:
    """Return the script class used by the code-switch bonus.

    Han and kana share ``"cjk"``; digit-only tokens belong to no script.
    """
    first = token[0]
    if "\uac00" <= first <= "\ud7a3":
        return "hangul"
    if _CJK_CHAR.match(first):
        return "cjk"
    return "" if token.isdigit() else "latin"


def doc_length(terms: dict[str, int]) -> int:
    """Return the BM25 document length without single Han/kana characters.

    Those unigrams repeat what the CJK bigrams already count.
    """
    return sum(
        frequency
        for term, frequency in terms.items()
        if len(term) > 1 or script(term) != "cjk"
    )


def bm25_scores(
    terms: list[str],
    postings: dict[str, dict[str, int]],
    doclens: dict[str, int],
    avgdl: float,
    n_docs: int,
) -> dict[str, float]:
    """Score terms against all indexed documents using Okapi BM25.

    The five independent values are the established public scoring API: query,
    inverted index, document lengths, corpus average, and corpus size. A query
    that mixes scripts multiplies each note by ``1 + SCRIPT_BONUS`` per extra
    script it matches; single-script queries are plain BM25.
    """
    scores: dict[str, float] = {}
    matched_scripts: dict[str, set[str]] = {}
    normalized_avgdl = avgdl or 1.0
    unique_terms = list(dict.fromkeys(terms))
    for term in unique_terms:
        post = postings.get(term)
        if not post:
            continue
        document_frequency = len(post)
        inverse_frequency = math.log(
            1 + (n_docs - document_frequency + 0.5) / (document_frequency + 0.5)
        )
        term_script = script(term)
        for note_slug, frequency in post.items():
            document_length = doclens.get(note_slug, normalized_avgdl)
            denominator = frequency + K1 * (
                1 - B + B * document_length / normalized_avgdl
            )
            scores[note_slug] = scores.get(note_slug, 0.0) + (
                inverse_frequency * frequency * (K1 + 1) / denominator
            )
            if term_script:
                matched_scripts.setdefault(note_slug, set()).add(term_script)
    if len({script(term) for term in unique_terms} - {""}) > 1:
        for note_slug in scores:
            extra = max(0, len(matched_scripts.get(note_slug, ())) - 1)
            scores[note_slug] *= 1 + SCRIPT_BONUS * extra
    return scores
