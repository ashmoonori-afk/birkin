"""Memory audit trail — transparency layer for wiki memory operations."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from birkin.memory.event_store import EventStore
    from birkin.memory.wiki import WikiMemory

logger = logging.getLogger(__name__)

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


class MemoryAuditor:
    """Records and queries memory operations for user transparency.

    Every wiki write and context-injection read is logged via EventStore
    so users can answer: "what does the AI know about me and why?"

    Usage::

        auditor = MemoryAuditor(event_store)
        auditor.log_write("concepts", "python", "auto_classified", 0.8, "from session s1")
        auditor.log_access("concepts", "python", "context injection", "s2")
        trail = auditor.get_page_history("concepts", "python")
    """

    def __init__(self, event_store: EventStore) -> None:
        self._store = event_store

    def log_write(
        self,
        category: str,
        slug: str,
        source: str,
        confidence: float,
        reason: str,
        session_id: str = "",
    ) -> None:
        """Log a memory page create/update."""
        from birkin.memory.events import RawEvent

        self._store.append(
            RawEvent(
                session_id=session_id,
                event_type="action",
                payload={
                    "audit_action": "memory_write",
                    "category": category,
                    "slug": slug,
                    "source": source,
                    "confidence": confidence,
                    "reason": reason,
                },
            )
        )

    def log_access(
        self,
        category: str,
        slug: str,
        reason: str,
        session_id: str = "",
    ) -> None:
        """Log when a memory page is read for context injection."""
        from birkin.memory.events import RawEvent

        self._store.append(
            RawEvent(
                session_id=session_id,
                event_type="action",
                payload={
                    "audit_action": "memory_access",
                    "category": category,
                    "slug": slug,
                    "reason": reason,
                },
            )
        )

    def get_page_history(self, category: str, slug: str) -> list[dict[str, Any]]:
        """Return audit trail for a specific memory page."""
        events = self._store.query(event_type="action", limit=1000)
        return [
            e.payload
            for e in events
            if e.payload.get("category") == category
            and e.payload.get("slug") == slug
            and e.payload.get("audit_action", "").startswith("memory_")
        ]

    def get_full_audit(self, limit: int = 200) -> list[dict[str, Any]]:
        """Return all memory audit events."""
        events = self._store.query(event_type="action", limit=limit)
        return [e.payload for e in events if e.payload.get("audit_action", "").startswith("memory_")]

    def explain_memory(
        self,
        category: str,
        slug: str,
        wiki: Optional[WikiMemory] = None,
    ) -> dict[str, Any]:
        """Human-readable explanation of a memory page."""
        history = self.get_page_history(category, slug)

        writes = [h for h in history if h.get("audit_action") == "memory_write"]
        accesses = [h for h in history if h.get("audit_action") == "memory_access"]
        creation = writes[0] if writes else {}

        content = ""
        if wiki:
            content = wiki.get_page(category, slug) or ""

        return {
            "category": category,
            "slug": slug,
            "what": content[:300] if content else "(page not found)",
            "why": creation.get("reason", "Unknown"),
            "source": creation.get("source", "unknown"),
            "confidence": creation.get("confidence", 0.5),
            "times_accessed": len(accesses),
            "times_updated": len(writes),
            "connections": _WIKILINK_RE.findall(content),
        }
