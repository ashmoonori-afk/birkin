"""Tests for ChatGPT conversation export parser."""

import pytest

from birkin.memory.importers.chatgpt import ChatGPTImporter
from birkin.memory.importers.base import auto_detect_and_parse


def _make_chatgpt_export(conversations: list[dict] | None = None) -> list[dict]:
    """Build a minimal ChatGPT export fixture."""
    if conversations:
        return conversations
    # Single conversation with 3 messages (system → user → assistant)
    return [
        {
            "id": "conv-001",
            "title": "Test Conversation",
            "create_time": 1700000000.0,
            "current_node": "node-3",
            "mapping": {
                "node-1": {
                    "id": "node-1",
                    "parent": None,
                    "message": {
                        "author": {"role": "system"},
                        "content": {"parts": ["You are a helpful assistant."]},
                        "create_time": 1700000000.0,
                        "metadata": {},
                    },
                },
                "node-2": {
                    "id": "node-2",
                    "parent": "node-1",
                    "message": {
                        "author": {"role": "user"},
                        "content": {"parts": ["Hello, what is Python?"]},
                        "create_time": 1700000001.0,
                        "metadata": {},
                    },
                },
                "node-3": {
                    "id": "node-3",
                    "parent": "node-2",
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {"parts": ["Python is a programming language."]},
                        "create_time": 1700000002.0,
                        "metadata": {"model_slug": "gpt-4"},
                    },
                },
            },
        }
    ]


class TestChatGPTDetect:
    def test_detect_valid(self):
        data = _make_chatgpt_export()
        assert ChatGPTImporter.detect(data) is True

    def test_detect_empty_list(self):
        assert ChatGPTImporter.detect([]) is False

    def test_detect_not_list(self):
        assert ChatGPTImporter.detect({"key": "value"}) is False

    def test_detect_missing_mapping(self):
        data = [{"current_node": "x"}]
        assert ChatGPTImporter.detect(data) is False

    def test_detect_mapping_without_current_node(self):
        """mapping only (no current_node) should still detect as ChatGPT."""
        data = [{"mapping": {"root": {}}}]
        assert ChatGPTImporter.detect(data) is True

    def test_detect_claude_format(self):
        data = [{"chat_messages": [{"sender": "human", "text": "hi"}]}]
        assert ChatGPTImporter.detect(data) is False


class TestChatGPTParse:
    def test_basic_parse(self):
        data = _make_chatgpt_export()
        importer = ChatGPTImporter()
        convs = importer.parse(data)

        assert len(convs) == 1
        conv = convs[0]
        assert conv.id == "conv-001"
        assert conv.title == "Test Conversation"
        assert conv.source == "chatgpt"
        assert len(conv.messages) == 3
        assert conv.messages[0].role == "system"
        assert conv.messages[1].role == "user"
        assert conv.messages[1].content == "Hello, what is Python?"
        assert conv.messages[2].role == "assistant"
        assert conv.messages[2].model == "gpt-4"

    def test_user_messages_property(self):
        data = _make_chatgpt_export()
        convs = ChatGPTImporter().parse(data)
        assert len(convs[0].user_messages) == 1
        assert convs[0].user_messages[0].content == "Hello, what is Python?"

    def test_timestamp_parsing(self):
        data = _make_chatgpt_export()
        convs = ChatGPTImporter().parse(data)
        assert convs[0].created_at is not None
        assert "2023-11" in convs[0].created_at

    def test_null_message_nodes(self):
        """Nodes with message=None should be skipped."""
        data = [
            {
                "id": "conv-002",
                "title": "With Null",
                "create_time": 1700000000.0,
                "current_node": "n2",
                "mapping": {
                    "n1": {"id": "n1", "parent": None, "message": None},
                    "n2": {
                        "id": "n2",
                        "parent": "n1",
                        "message": {
                            "author": {"role": "user"},
                            "content": {"parts": ["test"]},
                            "create_time": 1700000001.0,
                            "metadata": {},
                        },
                    },
                },
            }
        ]
        convs = ChatGPTImporter().parse(data)
        assert len(convs) == 1
        assert len(convs[0].messages) == 1

    def test_empty_content_skipped(self):
        data = [
            {
                "id": "conv-003",
                "title": "Empty",
                "create_time": 1700000000.0,
                "current_node": "n1",
                "mapping": {
                    "n1": {
                        "id": "n1",
                        "parent": None,
                        "message": {
                            "author": {"role": "user"},
                            "content": {"parts": [""]},
                            "create_time": 1700000001.0,
                            "metadata": {},
                        },
                    },
                },
            }
        ]
        convs = ChatGPTImporter().parse(data)
        assert len(convs) == 0  # No messages → no conversation

    def test_structured_content_parts(self):
        """Non-string parts (like image refs) should extract text if available."""
        data = [
            {
                "id": "conv-004",
                "title": "Structured",
                "create_time": 1700000000.0,
                "current_node": "n1",
                "mapping": {
                    "n1": {
                        "id": "n1",
                        "parent": None,
                        "message": {
                            "author": {"role": "user"},
                            "content": {
                                "parts": [
                                    "Here is an image:",
                                    {"content_type": "image", "text": "diagram.png"},
                                ]
                            },
                            "create_time": 1700000001.0,
                            "metadata": {},
                        },
                    },
                },
            }
        ]
        convs = ChatGPTImporter().parse(data)
        assert len(convs) == 1
        assert "diagram.png" in convs[0].messages[0].content

    def test_korean_content(self):
        data = [
            {
                "id": "conv-kr",
                "title": "한국어 대화",
                "create_time": 1700000000.0,
                "current_node": "n2",
                "mapping": {
                    "n1": {
                        "id": "n1",
                        "parent": None,
                        "message": {
                            "author": {"role": "user"},
                            "content": {"parts": ["파이썬이 뭐야?"]},
                            "create_time": 1700000001.0,
                            "metadata": {},
                        },
                    },
                    "n2": {
                        "id": "n2",
                        "parent": "n1",
                        "message": {
                            "author": {"role": "assistant"},
                            "content": {"parts": ["파이썬은 프로그래밍 언어입니다."]},
                            "create_time": 1700000002.0,
                            "metadata": {},
                        },
                    },
                },
            }
        ]
        convs = ChatGPTImporter().parse(data)
        assert len(convs) == 1
        assert convs[0].title == "한국어 대화"
        assert "파이썬이" in convs[0].messages[0].content

    def test_multiple_conversations(self):
        data = _make_chatgpt_export()
        # Add a second conversation
        data.append(
            {
                "id": "conv-002",
                "title": "Second",
                "create_time": 1700000100.0,
                "current_node": "n1",
                "mapping": {
                    "n1": {
                        "id": "n1",
                        "parent": None,
                        "message": {
                            "author": {"role": "user"},
                            "content": {"parts": ["Another question"]},
                            "create_time": 1700000100.0,
                            "metadata": {},
                        },
                    },
                },
            }
        )
        convs = ChatGPTImporter().parse(data)
        assert len(convs) == 2

    def test_parse_non_list(self):
        assert ChatGPTImporter().parse({"not": "a list"}) == []

    def test_branching_follows_current_node(self):
        """When a conversation has branches, we follow current_node path."""
        data = [
            {
                "id": "conv-branch",
                "title": "Branched",
                "create_time": 1700000000.0,
                "current_node": "branch-b",
                "mapping": {
                    "root": {"id": "root", "parent": None, "message": None},
                    "user-q": {
                        "id": "user-q",
                        "parent": "root",
                        "message": {
                            "author": {"role": "user"},
                            "content": {"parts": ["What is 2+2?"]},
                            "create_time": 1700000001.0,
                            "metadata": {},
                        },
                    },
                    "branch-a": {
                        "id": "branch-a",
                        "parent": "user-q",
                        "message": {
                            "author": {"role": "assistant"},
                            "content": {"parts": ["It is 4. (first attempt)"]},
                            "create_time": 1700000002.0,
                            "metadata": {},
                        },
                    },
                    "branch-b": {
                        "id": "branch-b",
                        "parent": "user-q",
                        "message": {
                            "author": {"role": "assistant"},
                            "content": {"parts": ["The answer is 4. (regenerated)"]},
                            "create_time": 1700000003.0,
                            "metadata": {},
                        },
                    },
                },
            }
        ]
        convs = ChatGPTImporter().parse(data)
        assert len(convs) == 1
        # Should follow branch-b (current_node), not branch-a
        assert "regenerated" in convs[0].messages[-1].content


class TestAutoDetect:
    def test_auto_detect_chatgpt(self):
        data = _make_chatgpt_export()
        convs = auto_detect_and_parse(data)
        assert len(convs) == 1
        assert convs[0].source == "chatgpt"

    def test_auto_detect_unknown(self):
        with pytest.raises(ValueError, match="Unrecognized"):
            auto_detect_and_parse([{"unknown": "format"}])
