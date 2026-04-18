"""Tests for Claude conversation export parser."""

import pytest

from birkin.memory.importers.claude import ClaudeImporter
from birkin.memory.importers.base import auto_detect_and_parse


def _make_claude_export(conversations: list[dict] | None = None) -> list[dict]:
    """Build a minimal Claude export fixture."""
    if conversations:
        return conversations
    return [
        {
            "uuid": "conv-uuid-001",
            "name": "Python 질문",
            "created_at": "2024-06-15T10:30:00Z",
            "updated_at": "2024-06-15T10:35:00Z",
            "chat_messages": [
                {
                    "uuid": "msg-001",
                    "text": "What is Python used for?",
                    "sender": "human",
                    "created_at": "2024-06-15T10:30:00Z",
                    "attachments": [],
                    "files": [],
                },
                {
                    "uuid": "msg-002",
                    "text": "Python is widely used for web development, data science, and automation.",
                    "sender": "assistant",
                    "created_at": "2024-06-15T10:30:05Z",
                    "attachments": [],
                    "files": [],
                },
            ],
        }
    ]


class TestClaudeDetect:
    def test_detect_valid(self):
        data = _make_claude_export()
        assert ClaudeImporter.detect(data) is True

    def test_detect_empty_list(self):
        assert ClaudeImporter.detect([]) is False

    def test_detect_not_list(self):
        assert ClaudeImporter.detect({"key": "value"}) is False

    def test_detect_no_chat_messages(self):
        data = [{"uuid": "x", "name": "y"}]
        assert ClaudeImporter.detect(data) is False

    def test_detect_empty_chat_messages(self):
        data = [{"chat_messages": []}]
        assert ClaudeImporter.detect(data) is False

    def test_detect_missing_sender(self):
        data = [{"chat_messages": [{"text": "hi"}]}]
        assert ClaudeImporter.detect(data) is False

    def test_detect_chatgpt_format(self):
        data = [{"mapping": {}, "current_node": "x"}]
        assert ClaudeImporter.detect(data) is False


class TestClaudeParse:
    def test_basic_parse(self):
        data = _make_claude_export()
        importer = ClaudeImporter()
        convs = importer.parse(data)

        assert len(convs) == 1
        conv = convs[0]
        assert conv.id == "conv-uuid-001"
        assert conv.title == "Python 질문"
        assert conv.source == "claude"
        assert conv.created_at == "2024-06-15T10:30:00Z"
        assert len(conv.messages) == 2
        assert conv.messages[0].role == "user"
        assert conv.messages[0].content == "What is Python used for?"
        assert conv.messages[1].role == "assistant"

    def test_user_messages_property(self):
        data = _make_claude_export()
        convs = ClaudeImporter().parse(data)
        assert len(convs[0].user_messages) == 1

    def test_empty_text_skipped(self):
        data = [
            {
                "uuid": "conv-002",
                "name": "Empty",
                "chat_messages": [
                    {"uuid": "m1", "text": "", "sender": "human", "created_at": "2024-01-01T00:00:00Z"},
                    {"uuid": "m2", "text": "  ", "sender": "assistant", "created_at": "2024-01-01T00:00:01Z"},
                ],
            }
        ]
        convs = ClaudeImporter().parse(data)
        assert len(convs) == 0  # No valid messages → no conversation

    def test_korean_content(self):
        data = [
            {
                "uuid": "conv-kr",
                "name": "한국어 테스트",
                "created_at": "2024-06-15T10:00:00Z",
                "chat_messages": [
                    {
                        "uuid": "m1",
                        "text": "Birkin 프로젝트의 메모리 시스템 설명해줘",
                        "sender": "human",
                        "created_at": "2024-06-15T10:00:00Z",
                    },
                    {
                        "uuid": "m2",
                        "text": "Birkin의 메모리 시스템은 위키 기반의 지식 저장소입니다.",
                        "sender": "assistant",
                        "created_at": "2024-06-15T10:00:05Z",
                    },
                ],
            }
        ]
        convs = ClaudeImporter().parse(data)
        assert len(convs) == 1
        assert convs[0].title == "한국어 테스트"
        assert "메모리 시스템" in convs[0].messages[0].content

    def test_multiple_conversations(self):
        data = _make_claude_export()
        data.append(
            {
                "uuid": "conv-002",
                "name": "Second Chat",
                "chat_messages": [
                    {"uuid": "m1", "text": "Another question", "sender": "human"},
                ],
            }
        )
        convs = ClaudeImporter().parse(data)
        assert len(convs) == 2

    def test_parse_non_list(self):
        assert ClaudeImporter().parse({"not": "a list"}) == []

    def test_untitled_conversation(self):
        data = [
            {
                "uuid": "conv-untitled",
                "name": None,
                "chat_messages": [
                    {"uuid": "m1", "text": "Hello", "sender": "human"},
                ],
            }
        ]
        convs = ClaudeImporter().parse(data)
        assert convs[0].title == "Untitled"

    def test_unknown_sender_skipped(self):
        data = [
            {
                "uuid": "conv-unk",
                "name": "Unknown",
                "chat_messages": [
                    {"uuid": "m1", "text": "Hello", "sender": "human"},
                    {"uuid": "m2", "text": "System msg", "sender": "system"},
                ],
            }
        ]
        convs = ClaudeImporter().parse(data)
        assert len(convs[0].messages) == 1  # system sender filtered out

    def test_timestamp_preserved(self):
        data = _make_claude_export()
        convs = ClaudeImporter().parse(data)
        assert convs[0].messages[0].timestamp == "2024-06-15T10:30:00Z"


class TestAutoDetectClaude:
    def test_auto_detect_claude(self):
        data = _make_claude_export()
        convs = auto_detect_and_parse(data)
        assert len(convs) == 1
        assert convs[0].source == "claude"
