"""LLM-based memory classifier for bilingual (Korean + English) input.

Replaces English-only heuristics that misclassify Korean input by using
a lightweight LLM call to decide whether a conversation turn should be
saved and how to categorise it.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from birkin.core.models import Message
from birkin.core.providers.base import Provider

logger = logging.getLogger(__name__)

_VALID_CATEGORIES = frozenset({"entities", "concepts", "sessions"})

_SYSTEM_PROMPT = """\
You are a memory classifier for a bilingual (Korean/English) AI assistant.

Given a user message and the assistant's response, decide:
1. Whether this exchange is worth saving to long-term memory.
2. If yes, classify it into exactly one category.

Categories:
- "entities": about a specific person, company, project, or organization
- "concepts": about an idea, technology, method, or domain knowledge
- "sessions": general conversation worth remembering for context

Rules:
- Trivial greetings, acknowledgments, or very short exchanges → should_save=false
- The message can be in ANY language (Korean, English, mixed). Judge by meaning, not by language.
- slug must be URL-safe ASCII (lowercase, hyphens, no spaces).
- tags: 1-5 short lowercase keywords.
- title: concise description (max 80 chars), in the same language as the user input.

Respond with ONLY valid JSON, no markdown fences, no extra text.

### Examples

User: "딥러닝에서 트랜스포머 아키텍처의 핵심 원리를 설명해줘"
Assistant: "트랜스포머는 셀프 어텐션 메커니즘을 기반으로..."
→ {"should_save": true, "category": "concepts",
   "slug": "transformer-architecture-principles",
   "title": "트랜스포머 아키텍처 핵심 원리",
   "tags": ["deep-learning", "transformer", "attention"]}

User: "Who is Jensen Huang?"
Assistant: "Jensen Huang is the co-founder and CEO of NVIDIA..."
→ {"should_save": true, "category": "entities",
   "slug": "jensen-huang-nvidia",
   "title": "Jensen Huang - NVIDIA CEO",
   "tags": ["nvidia", "jensen-huang", "ceo"]}

User: "안녕"
Assistant: "안녕하세요! 무엇을 도와드릴까요?"
→ {"should_save": false, "category": "sessions", "slug": "", "title": "", "tags": []}

User: "Can you help me plan my project architecture for a microservices migration?"
Assistant: "Sure! Here's a phased approach to migrating from monolith to microservices..."
→ {"should_save": true, "category": "sessions",
   "slug": "microservices-migration-plan",
   "title": "Microservices migration planning",
   "tags": ["architecture", "microservices", "migration"]}
"""


class MemoryClassifier:
    """Uses an LLM provider to classify conversation turns for memory storage."""

    def __init__(self, provider: Provider) -> None:
        self._provider = provider

    def classify(self, user_input: str, response: str) -> Optional[dict[str, Any]]:
        """Classify a conversation turn for memory storage.

        Returns a dict with keys: should_save, category, slug, title, tags.
        Returns None on any error (timeout, JSON parse failure, provider error)
        so the caller can fall back to heuristic classification.
        """
        messages = [
            Message(role="system", content=_SYSTEM_PROMPT),
            Message(
                role="user",
                content=(f"User: {user_input[:500]}\nAssistant: {response[:1000]}"),
            ),
        ]

        try:
            provider_response = self._provider.complete(messages)
            raw = (provider_response.content or "").strip()
            result = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.debug("Classifier JSON parse failed: %s", exc)
            return None
        except (ConnectionError, TimeoutError, RuntimeError, ValueError) as exc:
            logger.debug("Classifier provider call failed: %s", exc)
            return None

        return self._validate(result)

    @staticmethod
    def _validate(result: Any) -> Optional[dict[str, Any]]:
        """Validate and normalize the classifier output.

        Returns the validated dict or None if the structure is invalid.
        """
        if not isinstance(result, dict):
            logger.debug("Classifier returned non-dict: %s", type(result))
            return None

        required_keys = {"should_save", "category", "slug", "title", "tags"}
        if not required_keys.issubset(result.keys()):
            logger.debug("Classifier missing keys: %s", required_keys - result.keys())
            return None

        if not isinstance(result["should_save"], bool):
            logger.debug("should_save is not bool: %s", result["should_save"])
            return None

        if result["category"] not in _VALID_CATEGORIES:
            logger.debug("Invalid category: %s", result["category"])
            return None

        if not isinstance(result["slug"], str):
            return None

        if not isinstance(result["title"], str):
            return None

        if not isinstance(result["tags"], list):
            return None

        return {
            "should_save": result["should_save"],
            "category": result["category"],
            "slug": result["slug"],
            "title": result["title"],
            "tags": result["tags"],
        }
