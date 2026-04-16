"""Command parser — natural language to structured intent."""

from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel


class Intent(BaseModel):
    """Parsed intent from a natural language command."""

    kind: Literal["run_workflow", "ask_agent", "schedule", "recall", "search", "configure", "unknown"] = "unknown"
    target: Optional[str] = None
    params: dict[str, Any] = {}
    confidence: float = 0.0
    original: str = ""


# Keyword patterns for intent classification
_PATTERNS: list[tuple[str, str, list[str]]] = [
    ("run_workflow", "workflow", ["run workflow", "execute workflow", "start workflow", "워크플로우 실행"]),
    ("recall", "session", ["recall", "remember", "what did", "기억", "이전에", "지난번"]),
    ("schedule", "trigger", ["schedule", "every day", "every week", "every morning", "매일", "매주", "cron"]),
    ("search", "memory", ["search", "find", "look up", "검색", "찾아"]),
    ("configure", "settings", ["set ", "config", "change provider", "설정"]),
]


class CommandParser:
    """Parse natural language commands into structured intents.

    Uses keyword matching for fast, offline classification.
    Can be extended with LLM-based parsing for higher accuracy.

    Usage::

        parser = CommandParser()
        intent = parser.parse("run the weekly review workflow")
        # Intent(kind="run_workflow", target="weekly review", confidence=0.8)
    """

    def parse(self, utterance: str) -> Intent:
        """Parse a natural language utterance into an Intent."""
        text = utterance.strip()
        text_lower = text.lower()

        if not text:
            return Intent(kind="unknown", original=text)

        # Try keyword patterns
        for kind, default_target, keywords in _PATTERNS:
            for kw in keywords:
                if kw in text_lower:
                    target = self._extract_target(text, kw)
                    return Intent(
                        kind=kind,
                        target=target or default_target,
                        confidence=0.7,
                        original=text,
                    )

        # Default: treat as ask_agent
        return Intent(
            kind="ask_agent",
            target=None,
            params={"message": text},
            confidence=0.5,
            original=text,
        )

    @staticmethod
    def _extract_target(text: str, matched_keyword: str) -> Optional[str]:
        """Extract the target from text after the matched keyword."""
        idx = text.lower().find(matched_keyword)
        if idx == -1:
            return None
        after = text[idx + len(matched_keyword) :].strip()
        # Clean up common trailing words
        after = re.sub(r"\s+(please|now|지금|해줘|해 줘)$", "", after, flags=re.IGNORECASE).strip()
        return after if after else None
