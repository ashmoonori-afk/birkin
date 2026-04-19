"""Workflow recommender — analyses event history to suggest workflows."""

from __future__ import annotations

import datetime as dt
import logging
import math
import uuid
from collections import Counter
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from birkin.memory.event_store import EventStore
    from birkin.memory.wiki import WikiMemory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class RepetitionSignal(BaseModel, frozen=True):
    """A detected recurring pattern in user behaviour."""

    pattern_type: str  # "tool_repeat" | "topic_repeat" | "schedule_repeat"
    description: str
    frequency: int = 0
    last_seen: str = ""  # ISO timestamp
    related_events: list[str] = Field(default_factory=list)


class WorkflowSuggestion(BaseModel):
    """A scored workflow recommendation."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    description: str = ""
    confidence: float = 0.0
    source_signal: Optional[RepetitionSignal] = None
    draft_workflow: Optional[dict] = None
    sample_match: Optional[str] = None


# ---------------------------------------------------------------------------
# Recommender engine
# ---------------------------------------------------------------------------

_TOOL_REPEAT_THRESHOLD = 3
_TOPIC_REPEAT_THRESHOLD = 5
_SCORE_CLAMP_MAX = 1.0


class WorkflowRecommender:
    """Analyses memory + events to proactively suggest workflows.

    Usage::

        recommender = WorkflowRecommender(event_store, wiki)
        suggestions = await recommender.suggest(top_k=3)
    """

    def __init__(
        self,
        event_store: EventStore,
        wiki: Optional[WikiMemory] = None,
    ) -> None:
        self._store = event_store
        self._wiki = wiki
        self._dismissed_ids: set[str] = set()

    # -- public API ---------------------------------------------------------

    async def suggest(self, top_k: int = 3) -> list[WorkflowSuggestion]:
        """Generate ranked workflow suggestions from behavioural signals."""
        signals = await self.detect_repetitions()
        if not signals:
            return []

        suggestions: list[WorkflowSuggestion] = []
        for sig in signals:
            score = self._score_suggestion(sig)
            if score <= 0:
                continue
            suggestions.append(
                WorkflowSuggestion(
                    title=self._title_from_signal(sig),
                    description=sig.description,
                    confidence=score,
                    source_signal=sig,
                    draft_workflow=self._draft_template(sig),
                )
            )

        suggestions.sort(key=lambda s: s.confidence, reverse=True)

        # filter dismissed
        suggestions = [s for s in suggestions if s.id not in self._dismissed_ids]

        return suggestions[:top_k]

    async def detect_repetitions(self, days: int = 14) -> list[RepetitionSignal]:
        """Scan EventStore for repeated action patterns."""
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
        events = self._store.since(cutoff)
        if not events:
            return []

        signals: list[RepetitionSignal] = []

        # 1) Repeated tool calls
        tool_events = [e for e in events if e.event_type == "tool_call"]
        tool_counter: Counter[str] = Counter()
        tool_last: dict[str, str] = {}
        tool_ids: dict[str, list[str]] = {}
        for ev in tool_events:
            name = ev.payload.get("name", "unknown")
            tool_counter[name] += 1
            tool_last[name] = ev.timestamp
            tool_ids.setdefault(name, []).append(ev.id)

        for name, freq in tool_counter.items():
            if freq >= _TOOL_REPEAT_THRESHOLD:
                signals.append(
                    RepetitionSignal(
                        pattern_type="tool_repeat",
                        description=f"Tool '{name}' called {freq} times in {days} days",
                        frequency=freq,
                        last_seen=tool_last[name],
                        related_events=tool_ids[name][:10],
                    )
                )

        # 2) Repeated user message topics (simple keyword extraction)
        user_msgs = [
            e.payload.get("content", "") for e in events if e.event_type == "user_message" and e.payload.get("content")
        ]
        word_counter: Counter[str] = Counter()
        for msg in user_msgs:
            words = {w.lower() for w in msg.split() if len(w) > 3}
            word_counter.update(words)

        for word, freq in word_counter.most_common(10):
            if freq >= _TOPIC_REPEAT_THRESHOLD:
                signals.append(
                    RepetitionSignal(
                        pattern_type="topic_repeat",
                        description=f"Topic '{word}' mentioned {freq} times",
                        frequency=freq,
                        last_seen=events[-1].timestamp if events else "",
                    )
                )

        return signals

    # -- scoring ------------------------------------------------------------

    def _score_suggestion(
        self,
        signal: RepetitionSignal,
        feedback_action: Optional[str] = None,
    ) -> float:
        """Score = log(freq+1) * type_weight * recency_decay * feedback_mult."""
        base = math.log(signal.frequency + 1)

        type_weight = 1.5 if signal.pattern_type == "tool_repeat" else 1.0

        # recency decay
        if signal.last_seen:
            try:
                last = dt.datetime.fromisoformat(signal.last_seen)
                now = dt.datetime.now(dt.timezone.utc)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=dt.timezone.utc)
                days_ago = max((now - last).total_seconds() / 86400, 0)
            except (ValueError, TypeError):
                days_ago = 7.0
        else:
            days_ago = 7.0
        recency = math.exp(-0.1 * days_ago)

        # feedback multiplier (Phase 3)
        feedback_mult = (
            {
                "dismissed": 0.0,
                "deleted_after_use": 0.2,
                "accepted": 0.5,
                "modified": 1.3,
            }.get(feedback_action, 1.0)
            if feedback_action
            else 1.0
        )

        score = base * type_weight * recency * feedback_mult
        return min(score, _SCORE_CLAMP_MAX)

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _title_from_signal(signal: RepetitionSignal) -> str:
        if signal.pattern_type == "tool_repeat":
            tool = signal.description.split("'")[1] if "'" in signal.description else "tool"
            return f"Automate {tool} workflow"
        if signal.pattern_type == "topic_repeat":
            topic = signal.description.split("'")[1] if "'" in signal.description else "topic"
            return f"Create workflow for {topic}"
        return "Suggested workflow"

    @staticmethod
    def _draft_template(signal: RepetitionSignal) -> dict:
        """Build a minimal 3-node template: input → process → output."""
        return {
            "nodes": [
                {"id": "start", "type": "input", "config": {}},
                {"id": "process", "type": "llm", "config": {"prompt": signal.description}},
                {"id": "end", "type": "output", "config": {}},
            ],
            "edges": [
                {"from": "start", "to": "process"},
                {"from": "process", "to": "end"},
            ],
        }
