"""Base models and ABC for conversation importers."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ParsedMessage:
    """A single message extracted from a conversation export."""

    role: str  # "user", "assistant", "system", "tool"
    content: str
    timestamp: Optional[str] = None  # ISO 8601
    model: Optional[str] = None


@dataclass
class ParsedConversation:
    """A normalized conversation from any export format."""

    id: str
    title: str
    created_at: Optional[str] = None  # ISO 8601
    messages: list[ParsedMessage] = field(default_factory=list)
    source: str = "unknown"  # "chatgpt" or "claude"

    @property
    def user_messages(self) -> list[ParsedMessage]:
        return [m for m in self.messages if m.role == "user"]

    @property
    def message_count(self) -> int:
        return len(self.messages)


class ConversationImporter(abc.ABC):
    """Abstract base class for conversation export parsers."""

    @classmethod
    @abc.abstractmethod
    def detect(cls, data: dict | list) -> bool:
        """Return True if the decoded JSON matches this format."""

    @abc.abstractmethod
    def parse(self, data: dict | list) -> list[ParsedConversation]:
        """Parse decoded JSON into a list of normalized conversations."""


def auto_detect_and_parse(data: dict | list) -> list[ParsedConversation]:
    """Auto-detect format and parse conversations.

    Tries each importer's detect() method and uses the first match.
    Raises ValueError if no format is recognized.
    """
    from birkin.memory.importers.chatgpt import ChatGPTImporter
    from birkin.memory.importers.claude import ClaudeImporter

    importers: list[type[ConversationImporter]] = [ChatGPTImporter, ClaudeImporter]

    for importer_cls in importers:
        if importer_cls.detect(data):
            return importer_cls().parse(data)

    raise ValueError(
        "Unrecognized conversation export format. Supported: ChatGPT (conversations.json), Claude (export JSON)."
    )
