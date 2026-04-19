"""Claude conversation export parser.

Anthropic's export format:
  - Top-level: list of conversation objects
  - Each conversation has: uuid, name, created_at, updated_at, chat_messages
  - chat_messages is a list of {uuid, text, sender, created_at, attachments, files}
  - sender is "human" or "assistant"
"""

from __future__ import annotations

from typing import Any, Optional

from birkin.memory.importers.base import ConversationImporter, ParsedConversation, ParsedMessage


class ClaudeImporter(ConversationImporter):
    """Parse Anthropic Claude conversation export."""

    @classmethod
    def detect(cls, data: dict | list) -> bool:
        """Detect Claude format by checking for chat_messages with sender fields.

        Scans up to the first 5 conversations since some may have empty messages.
        """
        if not isinstance(data, list) or len(data) == 0:
            return False

        for sample in data[:5]:
            if not isinstance(sample, dict):
                continue
            messages = sample.get("chat_messages", [])
            if not isinstance(messages, list) or len(messages) == 0:
                continue
            first_msg = messages[0]
            if isinstance(first_msg, dict) and "sender" in first_msg:
                return True

        # Fallback: if conversations have "chat_messages" key at all, it's likely Claude
        if isinstance(data[0], dict) and "chat_messages" in data[0] and "uuid" in data[0]:
            return True

        return False

    def parse(self, data: dict | list) -> list[ParsedConversation]:
        if not isinstance(data, list):
            return []

        conversations: list[ParsedConversation] = []
        for conv_obj in data:
            conv = self._parse_one(conv_obj)
            if conv and conv.messages:
                conversations.append(conv)
        return conversations

    def _parse_one(self, obj: dict[str, Any]) -> Optional[ParsedConversation]:
        chat_messages = obj.get("chat_messages", [])
        if not isinstance(chat_messages, list):
            return None

        messages: list[ParsedMessage] = []
        for msg in chat_messages:
            if not isinstance(msg, dict):
                continue

            sender = msg.get("sender", "")
            role = self._normalize_sender(sender)
            if not role:
                continue

            text = msg.get("text", "")
            # Fallback: extract from content array if text is empty
            if not text and isinstance(msg.get("content"), list):
                parts = [c.get("text", "") for c in msg["content"] if isinstance(c, dict) and c.get("text")]
                text = "\n".join(parts)
            if not text or not text.strip():
                continue

            timestamp = msg.get("created_at")
            messages.append(
                ParsedMessage(
                    role=role,
                    content=text.strip(),
                    timestamp=timestamp,
                )
            )

        conv_id = obj.get("uuid", "")
        title = obj.get("name", "Untitled") or "Untitled"
        created_at = obj.get("created_at")

        return ParsedConversation(
            id=str(conv_id),
            title=title,
            created_at=created_at,
            messages=messages,
            source="claude",
        )

    @staticmethod
    def _normalize_sender(sender: str) -> str:
        mapping = {
            "human": "user",
            "assistant": "assistant",
        }
        return mapping.get(sender, "")
