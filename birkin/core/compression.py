"""LLM-based conversation compression for context window management."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from typing import TYPE_CHECKING

from birkin.core.models import Message

if TYPE_CHECKING:
    from birkin.core.providers.base import Provider

_SUMMARIZE_SYSTEM_PROMPT = (
    "Summarize the following conversation in 3-5 sentences, preserving: "
    "user goals, decisions made, key facts, unresolved questions. "
    "Be concise and factual."
)

_MAX_CACHE_SIZE = 128
_summary_cache: OrderedDict[str, str] = OrderedDict()


def _cache_key(messages: list[Message]) -> str:
    """Compute SHA-256 hash of message contents for cache lookup."""
    parts = [json.dumps({"role": m.role, "content": m.content}, sort_keys=True) for m in messages]
    blob = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _build_transcript(messages: list[Message]) -> str:
    """Build a plain-text transcript from a list of messages."""
    lines: list[str] = []
    for msg in messages:
        label = msg.role.upper()
        lines.append(f"{label}: {msg.content}")
    return "\n".join(lines)


def summarize_messages(
    messages: list[Message],
    provider: Provider,
    model: str | None = None,
) -> str | None:
    """Summarize a block of conversation messages via the provider.

    Returns the summary text on success, or None on any error so
    the caller can fall back to the old head+tail truncation.
    """
    if not messages:
        return None

    transcript = _build_transcript(messages)

    try:
        response = provider.complete(
            [
                Message(role="system", content=_SUMMARIZE_SYSTEM_PROMPT),
                Message(role="user", content=transcript),
            ],
        )
        content = response.content
        if content and content.strip():
            return content.strip()
        return None
    except Exception:
        return None


def summarize_or_cache(
    messages: list[Message],
    provider: Provider,
) -> str | None:
    """Return a cached summary or generate one via the provider.

    Cache hits avoid redundant LLM calls when the same middle block
    is compressed repeatedly within a session.
    """
    if not messages:
        return None

    key = _cache_key(messages)

    cached = _summary_cache.get(key)
    if cached is not None:
        return cached

    summary = summarize_messages(messages, provider)
    if summary is not None:
        _summary_cache[key] = summary
        if len(_summary_cache) > _MAX_CACHE_SIZE:
            _summary_cache.popitem(last=False)
    return summary
