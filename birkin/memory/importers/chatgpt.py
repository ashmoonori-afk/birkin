"""ChatGPT conversation export parser.

OpenAI's conversations.json structure:
  - Top-level: list of conversation objects
  - Each conversation has a `mapping` dict (UUID → node)
  - Each node has `message` (nullable) with author.role, content.parts, create_time
  - Messages form a DAG; `current_node` points to the latest leaf
  - We walk from current_node backward through parent pointers to get the active thread
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from birkin.memory.importers.base import ConversationImporter, ParsedConversation, ParsedMessage


class ChatGPTImporter(ConversationImporter):
    """Parse OpenAI ChatGPT conversation export."""

    @classmethod
    def detect(cls, data: dict | list) -> bool:
        """Detect ChatGPT format by checking for mapping (current_node optional)."""
        if not isinstance(data, list) or len(data) == 0:
            return False
        sample = data[0]
        return isinstance(sample, dict) and "mapping" in sample

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
        mapping = obj.get("mapping")
        if not mapping:
            return None

        current_node = obj.get("current_node")

        if current_node:
            # Walk from current_node backward to root to get the active thread
            chain: list[str] = []
            node_id = current_node
            visited: set[str] = set()
            while node_id and node_id not in visited:
                visited.add(node_id)
                chain.append(node_id)
                node = mapping.get(node_id, {})
                node_id = node.get("parent")
            chain.reverse()
        else:
            # Fallback: iterate mapping in insertion order (all nodes)
            chain = list(mapping.keys())

        # Extract messages from chain
        messages: list[ParsedMessage] = []
        for nid in chain:
            node = mapping.get(nid, {})
            msg = node.get("message")
            if msg is None:
                continue

            author = msg.get("author", {})
            role = self._normalize_role(author.get("role", ""))
            if not role:
                continue

            content = self._extract_content(msg)
            if not content:
                continue

            timestamp = self._parse_timestamp(msg.get("create_time"))
            model = msg.get("metadata", {}).get("model_slug")

            messages.append(
                ParsedMessage(
                    role=role,
                    content=content,
                    timestamp=timestamp,
                    model=model,
                )
            )

        # Build conversation
        title = obj.get("title", "Untitled")
        create_time = obj.get("create_time")
        created_at = self._parse_timestamp(create_time)
        conv_id = obj.get("id", obj.get("conversation_id", ""))

        return ParsedConversation(
            id=str(conv_id),
            title=title or "Untitled",
            created_at=created_at,
            messages=messages,
            source="chatgpt",
        )

    @staticmethod
    def _normalize_role(role: str) -> str:
        mapping = {
            "user": "user",
            "assistant": "assistant",
            "system": "system",
            "tool": "tool",
        }
        return mapping.get(role, "")

    @staticmethod
    def _extract_content(msg: dict[str, Any]) -> str:
        """Extract text content from message.content.parts."""
        content_obj = msg.get("content", {})
        parts = content_obj.get("parts", [])

        text_parts: list[str] = []
        for part in parts:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict):
                # Image, code, or other structured content
                text = part.get("text", "")
                if text:
                    text_parts.append(text)

        return "\n".join(text_parts).strip()

    @staticmethod
    def _parse_timestamp(ts: float | int | None) -> Optional[str]:
        if ts is None:
            return None
        try:
            return dt.datetime.fromtimestamp(float(ts), tz=dt.timezone.utc).isoformat()
        except (ValueError, TypeError, OSError):
            return None
