"""Memory compiler — transforms raw events into structured wiki pages.

Implements the core of 'knowledge accumulation': interactions across
many agents consolidate into the user's knowledge asset.
"""

from __future__ import annotations

import logging
from typing import Optional

from birkin.memory.event_store import EventStore
from birkin.memory.events import RawEvent
from birkin.memory.wiki import WikiMemory

logger = logging.getLogger(__name__)


class CompileResult:
    """Result of a compilation run."""

    def __init__(self) -> None:
        self.pages_created: list[str] = []
        self.pages_updated: list[str] = []
        self.events_processed: int = 0


class MemoryCompiler:
    """Compiles raw events into Wiki Memory pages.

    Scans the EventStore for uncompiled events, extracts structured
    information, and writes/updates wiki pages.

    Usage::

        compiler = MemoryCompiler(event_store, wiki_memory)
        result = compiler.compile_session("session-123")
    """

    def __init__(self, event_store: EventStore, memory: WikiMemory) -> None:
        self._store = event_store
        self._memory = memory

    def compile_session(self, session_id: str) -> CompileResult:
        """Compile all events from a session into a wiki page.

        Creates a session summary page in the sessions/ category.
        """
        result = CompileResult()
        events = self._store.query(session_id=session_id, limit=500)
        if not events:
            return result

        result.events_processed = len(events)

        # Build session summary
        user_messages = [e for e in events if e.event_type == "user_message"]
        assistant_messages = [e for e in events if e.event_type == "assistant_message"]
        tool_calls = [e for e in events if e.event_type == "tool_call"]
        llm_calls = [e for e in events if e.event_type == "llm_call"]

        # Calculate totals
        total_tokens = sum((e.tokens.tokens_in + e.tokens.tokens_out) if e.tokens else 0 for e in events)
        total_cost = sum(e.tokens.cost_usd if e.tokens else 0.0 for e in events)
        providers_used = list({e.provider for e in events if e.provider})

        # Build page content
        parts = [f"# Session: {session_id[:12]}\n"]
        parts.append(f"**Events:** {len(events)} | **Tokens:** {total_tokens} | **Cost:** ${total_cost:.4f}")
        parts.append(f"**Providers:** {', '.join(providers_used) if providers_used else 'none'}")
        parts.append(f"**Tools used:** {len(tool_calls)}\n")

        if user_messages:
            parts.append("## Conversation\n")
            for msg in user_messages[:20]:  # Cap at 20
                text = msg.payload.get("content", "")[:200]
                parts.append(f"**User:** {text}\n")

        if tool_calls:
            parts.append("## Tool Calls\n")
            for tc in tool_calls[:10]:
                name = tc.payload.get("name", "unknown")
                outcome = tc.outcome
                parts.append(f"- `{name}` → {outcome}")

        content = "\n".join(parts)
        slug = f"session-{session_id[:12]}"

        existing = self._memory.get_page("sessions", slug)
        if existing:
            self._memory.ingest("sessions", slug, content)
            result.pages_updated.append(slug)
        else:
            self._memory.ingest("sessions", slug, content)
            result.pages_created.append(slug)

        logger.info("Compiled session %s: %d events → %s", session_id[:12], len(events), slug)
        return result

    def extract_entities(self, events: list[RawEvent]) -> list[dict]:
        """Extract entity mentions from events.

        Returns list of dicts with 'name', 'category', 'context'.
        """
        entities: list[dict] = []
        seen: set[str] = set()

        for event in events:
            content = event.payload.get("content", "")
            if not content or len(content) < 20:
                continue

            # Simple heuristic: look for capitalized multi-word phrases
            words = content.split()
            for i, word in enumerate(words):
                if word[0:1].isupper() and len(word) > 2 and word.isalpha():
                    # Check for multi-word entity (2-3 consecutive capitalized words)
                    phrase_words = [word]
                    for j in range(i + 1, min(i + 3, len(words))):
                        if words[j][0:1].isupper() and words[j].isalpha():
                            phrase_words.append(words[j])
                        else:
                            break
                    if len(phrase_words) >= 2:
                        name = " ".join(phrase_words)
                        if name not in seen:
                            seen.add(name)
                            entities.append({
                                "name": name,
                                "category": "entities",
                                "context": content[:100],
                            })

        # Korean proper noun extraction (optional kiwipiepy)
        try:
            from kiwipiepy import Kiwi

            kiwi = Kiwi()
            for event in events:
                content = event.payload.get("content", "")
                if not content or len(content) < 10:
                    continue
                for token in kiwi.tokenize(content):
                    if token.tag == "NNP" and len(token.form) >= 2:
                        name = token.form
                        if name not in seen:
                            seen.add(name)
                            entities.append({
                                "name": name,
                                "category": "entities",
                                "context": content[:100],
                            })
        except ImportError:
            pass  # kiwipiepy not installed — skip Korean NER

        return entities

    def compile_daily(self, date_str: str) -> CompileResult:
        """Compile all events from a specific date into a digest page.

        Args:
            date_str: ISO date string (e.g. "2026-04-16").
        """
        result = CompileResult()
        start = f"{date_str}T00:00:00"
        end = f"{date_str}T23:59:59"

        all_events = self._store.since(start)
        events = [e for e in all_events if e.timestamp <= end]

        if not events:
            return result

        result.events_processed = len(events)

        # Aggregate stats
        sessions = list({e.session_id for e in events})
        total_tokens = sum((e.tokens.tokens_in + e.tokens.tokens_out) if e.tokens else 0 for e in events)
        total_cost = sum(e.tokens.cost_usd if e.tokens else 0.0 for e in events)
        providers = list({e.provider for e in events if e.provider})

        parts = [f"# Daily Digest: {date_str}\n"]
        parts.append(f"**Sessions:** {len(sessions)} | **Events:** {len(events)}")
        parts.append(f"**Tokens:** {total_tokens} | **Cost:** ${total_cost:.4f}")
        parts.append(f"**Providers:** {', '.join(providers)}\n")

        parts.append("## Sessions\n")
        for sid in sessions[:10]:
            session_events = [e for e in events if e.session_id == sid]
            parts.append(f"- `{sid[:12]}`: {len(session_events)} events")

        content = "\n".join(parts)
        slug = f"digest-{date_str}"
        self._memory.ingest("digests", slug, content)
        result.pages_created.append(slug)

        logger.info("Compiled daily digest %s: %d events", date_str, len(events))
        return result
