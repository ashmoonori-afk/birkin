"""Does the cited source actually say that?

birkin already ships skills telling the model to cite: ``fact-checking``
("verify a claim against 2+ primary sources") and ``deep-research``
("synthesize sources into a cited report"). Both instruct; neither can check.
That asymmetry is the whole problem, because a model told to cite WILL cite --
it will attach a plausible URL to a sentence that URL does not support, and no
amount of further instruction detects the times it has.

So this is code. Given claims and the text actually fetched from each source,
decide per claim whether some source states it, and name the ones where none
does.

The matching is lexical: overlap of content words, and agreement on the numbers
and years that carry most of a factual claim's weight. It cannot read, and it
does not pretend to -- a claim supported only by paraphrase comes back
unsupported, which costs a re-check. That direction is the cheap error. The
expensive one is blessing a citation that says nothing of the kind, which puts
a false statement in front of the user wearing a footnote.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Enough overlap to believe the sentence is about the same thing.
_MIN_OVERLAP = 0.6
# Words that carry no evidence either way; matching on them alone is noise.
_STOPWORDS = frozenset("""
a an and are as at be by for from has have in is it its of on or that the to
was were will with this these those there here how what when where which who
""".split())

# Months are the part of a date that carries no digits, so a digits-only
# guard rates "closes 30 September" and "closes 30 October" as agreeing --
# they share 30 and 2026. A wrong month is a wrong fact.
_MONTHS = frozenset("""
january february march april may june july august september october
november december jan feb mar apr jun jul aug sep sept oct nov dec
월 일 년
""".split())

_WORD_RE = re.compile(r"[0-9]+(?:[.,][0-9]+)*|[^\W\d_]+", re.UNICODE)
_NUMBER_RE = re.compile(r"[0-9]+(?:[.,][0-9]+)*")
_SENTENCE_RE = re.compile(r"[^.!?。\n]+[.!?。]?")


@dataclass(frozen=True, slots=True)
class ClaimCheck:
    """One claim, and the sentence (if any) that supports it."""
    claim: str
    supported: bool
    source_url: str = ""
    quote: str = ""
    score: float = 0.0


@dataclass(slots=True)
class Report:
    checks: list[ClaimCheck] = field(default_factory=list)

    @property
    def supported_count(self) -> int:
        return sum(1 for c in self.checks if c.supported)

    @property
    def unsupported(self) -> list[ClaimCheck]:
        return [c for c in self.checks if not c.supported]

    @property
    def all_supported(self) -> bool:
        """Every claim checked out -- and there was at least one to check.

        No claims is not a pass. An empty report reading "all supported" is how
        an unverified answer acquires a clean bill of health.
        """
        return bool(self.checks) and not self.unsupported

    def render(self) -> str:
        if not self.checks:
            return "No claims were submitted for verification."
        lines = [f"{self.supported_count}/{len(self.checks)} claims supported "
                 f"by the sources provided.", ""]
        for check in self.checks:
            if check.supported:
                lines.append(f"SUPPORTED  {check.claim}")
                lines.append(f"           {check.source_url}")
                lines.append(f"           \u201c{check.quote.strip()[:220]}\u201d")
            else:
                lines.append(f"UNSUPPORTED  {check.claim}")
                lines.append("           no provided source states this; "
                             "fetch one that does, or drop the claim")
            lines.append("")
        return "\n".join(lines).rstrip()


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text or "")
            if w.lower() not in _STOPWORDS}


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER_RE.findall(text or "")}


def _months(text: str) -> set[str]:
    """Month names, normalised so 'Sept' and 'September' are one thing."""
    found = set()
    for word in _WORD_RE.findall(text or ""):
        lowered = word.lower()
        if lowered in _MONTHS:
            found.add(lowered[:3])
    return found


def _score(claim_words: set[str], claim_numbers: set[str],
           sentence: str) -> float:
    """How much of the claim this sentence accounts for, 0..1.

    A claim carrying numbers the sentence does not have scores zero outright:
    "closes 30 September" must never be evidence for "closes 30 October", and
    word overlap alone would rate those nearly identical.
    """
    if not claim_words:
        return 0.0
    sentence_words = _words(sentence)
    if claim_numbers and not claim_numbers <= _numbers(sentence):
        return 0.0
    claim_months = _months(" ".join(claim_words))
    if claim_months and not claim_months <= _months(sentence):
        return 0.0
    return len(claim_words & sentence_words) / len(claim_words)


def check_claim(claim: str, sources: list[dict[str, Any]]) -> ClaimCheck:
    """The best supporting sentence across ``sources``, or an unsupported verdict."""
    claim_words = _words(claim)
    claim_numbers = _numbers(claim)
    best = ClaimCheck(claim=claim, supported=False)
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "")
        for sentence in _SENTENCE_RE.findall(str(source.get("text") or "")):
            sentence = sentence.strip()
            if not sentence:
                continue
            score = _score(claim_words, claim_numbers, sentence)
            if score > best.score:
                best = ClaimCheck(claim=claim, supported=score >= _MIN_OVERLAP,
                                  source_url=url if score >= _MIN_OVERLAP else "",
                                  quote=sentence if score >= _MIN_OVERLAP else "",
                                  score=score)
    return best


def verify(claims: list[str], sources: list[dict[str, Any]]) -> Report:
    """Check every claim against every source."""
    return Report([check_claim(str(c), sources) for c in claims or []
                   if str(c).strip()])
