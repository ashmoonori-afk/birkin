"""Ladder-of-inference gate: does the final reply trace to observed evidence?

A model reporting "tests passed" is only trustworthy when something in the
session actually said so. :mod:`birkin.grounded` already scores claims
against fetched web sources; this module points the same scorer at a
different corpus -- the tool outputs of the current session -- so a factual
sentence in the final reply must find support in something the agent really
observed.

Observe-only by default: the runtime hook (``evidence_gate_enabled``, default
False) logs supported/unsupported counts to the ledger without touching the
reply. ``annotate`` exists for surfaces that want the visible footer once the
signal has proven trustworthy. Fail-open everywhere: an internal error must
never break or rewrite a turn. (.plans/thinking-frameworks.md item 3)

Pure standard library.
"""

from __future__ import annotations

import re
from typing import Any

from . import grounded

_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?")

# A sentence is a checkable claim when it carries a factual anchor: a number,
# a path, a pass/fail verdict, or a version string. Everything else is
# opinion or narration, and checking it would only manufacture noise.
_FACT_MARK_RE = re.compile(
    r"([0-9]|[/\\][\w.-]+|\.(py|md|json|toml|yml|yaml|txt)\b"
    r"|\bpassed\b|\bfailed\b|\bfailing\b|\berror\b|\bversion\b|\bv[0-9])",
    re.IGNORECASE)

_OPINION_RE = re.compile(
    r"^(i think|i believe|maybe|perhaps|probably|we should|let's|lets"
    r"|consider|note that|in my view)",
    re.IGNORECASE)


def extract_claims(reply: str) -> list[str]:
    """Sentences of ``reply`` worth checking against session evidence."""
    claims: list[str] = []
    for raw in _SENTENCE_RE.findall(reply or ""):
        sentence = raw.strip().strip("-*#>` ").strip()
        if len(sentence) < 8 or sentence.endswith("?"):
            continue
        if _OPINION_RE.match(sentence):
            continue
        if _FACT_MARK_RE.search(sentence):
            claims.append(sentence)
    return claims


def collect_tool_outputs(messages: list[dict[str, Any]]) -> list[str]:
    """Pull every tool_result text out of an agent-style message history."""
    texts: list[str] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) \
                    or block.get("type") != "tool_result":
                continue
            inner = block.get("content")
            if isinstance(inner, str):
                texts.append(inner)
            elif isinstance(inner, list):
                texts.extend(
                    str(part.get("text") or "") for part in inner
                    if isinstance(part, dict) and part.get("type") == "text")
    return [t for t in texts if t.strip()]


def verify_reply(reply: str,
                 tool_outputs: list[str]) -> grounded.Report:
    """Score the reply's claims against the session's tool outputs."""
    sources = [{"url": f"tool:{i}", "text": text}
               for i, text in enumerate(tool_outputs or [])]
    return grounded.verify(extract_claims(reply), sources)


def annotate(reply: str, report: grounded.Report, *,
             threshold: int = 0) -> str:
    """Append the ASCII unverified-claims footer; never rewrite the body."""
    try:
        unsupported = len(report.unsupported)
    except Exception:
        return reply
    if unsupported <= threshold:
        return reply
    return (f"{reply}\n\nunverified: {unsupported} claim(s) "
            "lack session evidence")
