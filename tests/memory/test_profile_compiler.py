"""Tests for ProfileCompiler — LLM-based conversation analysis."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from birkin.memory.importers.base import ParsedConversation, ParsedMessage
from birkin.memory.profile_compiler import ProfileCompiler, ProfileCompileResult, ProgressInfo
from birkin.memory.wiki import WikiMemory


def _make_conversations(count: int = 5) -> list[ParsedConversation]:
    """Create fixture conversations."""
    convs = []
    for i in range(count):
        convs.append(
            ParsedConversation(
                id=f"conv-{i:03d}",
                title=f"Conversation {i}",
                created_at=f"2024-06-{15 + i}T10:00:00Z",
                messages=[
                    ParsedMessage(role="user", content=f"I'm working on project Alpha using Python and FastAPI"),
                    ParsedMessage(role="assistant", content=f"That sounds great! Let me help."),
                    ParsedMessage(role="user", content=f"I need to optimize the database queries"),
                ],
                source="chatgpt",
            )
        )
    return convs


def _make_fake_provider(response_json: dict | None = None) -> MagicMock:
    """Create a mock provider that returns JSON."""
    provider = MagicMock()
    if response_json is None:
        response_json = {
            "job_role": "Backend Developer",
            "expertise_areas": ["Python", "FastAPI", "Database Optimization"],
            "interests": ["AI", "Web Development"],
            "active_projects": ["Project Alpha"],
            "tools_and_tech": ["Python", "FastAPI", "PostgreSQL"],
            "decision_patterns": ["Data-driven decisions"],
            "communication_style": "Concise and technical",
            "key_people": ["Team Lead"],
        }
    response = MagicMock()
    response.content = json.dumps(response_json, ensure_ascii=False)
    provider.complete.return_value = response
    return provider


def _make_wiki() -> WikiMemory:
    """Create a temp WikiMemory."""
    tmpdir = tempfile.mkdtemp()
    wiki = WikiMemory(root=tmpdir)
    wiki.init()
    return wiki


class TestProfileCompilerBasic:
    def test_compile_creates_pages(self):
        wiki = _make_wiki()
        provider = _make_fake_provider()
        compiler = ProfileCompiler(provider, wiki)

        result = compiler.compile_profile(_make_conversations(3), batch_size=10)

        assert isinstance(result, ProfileCompileResult)
        assert len(result.pages_created) >= 1
        assert "entities/user-profile" in result.pages_created
        assert result.conversations_processed == 3
        assert result.batches_succeeded >= 1
        assert result.batches_failed == 0

    def test_user_profile_page_content(self):
        wiki = _make_wiki()
        provider = _make_fake_provider()
        compiler = ProfileCompiler(provider, wiki)
        compiler.compile_profile(_make_conversations(2), batch_size=10)

        page = wiki.get_page("entities", "user-profile")
        assert page is not None
        assert "Backend Developer" in page

    def test_expertise_page_created(self):
        wiki = _make_wiki()
        provider = _make_fake_provider()
        compiler = ProfileCompiler(provider, wiki)
        compiler.compile_profile(_make_conversations(2), batch_size=10)

        page = wiki.get_page("concepts", "user-expertise")
        assert page is not None
        assert "Python" in page

    def test_interests_page_created(self):
        wiki = _make_wiki()
        provider = _make_fake_provider()
        compiler = ProfileCompiler(provider, wiki)
        compiler.compile_profile(_make_conversations(2), batch_size=10)

        page = wiki.get_page("concepts", "user-interests")
        assert page is not None
        assert "AI" in page

    def test_projects_page_created(self):
        wiki = _make_wiki()
        provider = _make_fake_provider()
        compiler = ProfileCompiler(provider, wiki)
        compiler.compile_profile(_make_conversations(2), batch_size=10)

        page = wiki.get_page("concepts", "user-projects")
        assert page is not None
        assert "Project Alpha" in page

    def test_style_page_created(self):
        wiki = _make_wiki()
        provider = _make_fake_provider()
        compiler = ProfileCompiler(provider, wiki)
        compiler.compile_profile(_make_conversations(2), batch_size=10)

        page = wiki.get_page("concepts", "user-style")
        assert page is not None
        assert "Concise" in page


class TestProfileCompilerBatching:
    def test_batching_with_small_batch_size(self):
        wiki = _make_wiki()
        provider = _make_fake_provider()
        compiler = ProfileCompiler(provider, wiki)

        result = compiler.compile_profile(_make_conversations(10), batch_size=3)

        # 10 conversations / 3 per batch = 4 batches
        assert result.batches_total == 4
        assert result.batches_succeeded == 4
        # 4 batch calls + 1 merge call = 5 total LLM calls
        assert provider.complete.call_count == 5

    def test_single_batch_no_merge(self):
        wiki = _make_wiki()
        provider = _make_fake_provider()
        compiler = ProfileCompiler(provider, wiki)

        result = compiler.compile_profile(_make_conversations(3), batch_size=10)

        assert result.batches_total == 1
        # Only 1 batch call, no merge needed
        assert provider.complete.call_count == 1

    def test_max_conversations_cap(self):
        wiki = _make_wiki()
        provider = _make_fake_provider()
        compiler = ProfileCompiler(provider, wiki)

        result = compiler.compile_profile(
            _make_conversations(100), batch_size=50, max_conversations=20
        )

        assert result.conversations_processed == 20


class TestProfileCompilerProgress:
    def test_progress_callback(self):
        wiki = _make_wiki()
        provider = _make_fake_provider()
        compiler = ProfileCompiler(provider, wiki)
        progress_updates: list[ProgressInfo] = []

        compiler.compile_profile(
            _make_conversations(5),
            batch_size=3,
            on_progress=lambda p: progress_updates.append(p),
        )

        phases = [p.phase for p in progress_updates]
        assert "analyzing" in phases
        assert "compiling" in phases


class TestProfileCompilerErrors:
    def test_batch_failure_continues(self):
        wiki = _make_wiki()
        provider = MagicMock()
        response_ok = MagicMock()
        response_ok.content = json.dumps({
            "job_role": "Developer",
            "expertise_areas": ["Python"],
            "interests": [],
            "active_projects": [],
            "tools_and_tech": [],
            "decision_patterns": [],
            "communication_style": None,
            "key_people": [],
        })

        # First batch fails, second succeeds
        provider.complete.side_effect = [
            Exception("Rate limited"),
            response_ok,
        ]
        compiler = ProfileCompiler(provider, wiki)

        result = compiler.compile_profile(_make_conversations(6), batch_size=3)

        assert result.batches_failed == 1
        assert result.batches_succeeded == 1
        assert len(result.errors) >= 1
        assert len(result.pages_created) >= 1

    def test_all_batches_fail(self):
        wiki = _make_wiki()
        provider = MagicMock()
        provider.complete.side_effect = Exception("API down")
        compiler = ProfileCompiler(provider, wiki)

        result = compiler.compile_profile(_make_conversations(3), batch_size=10)

        assert result.batches_failed == 1
        assert result.batches_succeeded == 0
        assert len(result.pages_created) == 0
        assert "All batches failed" in result.errors[-1]

    def test_empty_conversations(self):
        wiki = _make_wiki()
        provider = _make_fake_provider()
        compiler = ProfileCompiler(provider, wiki)

        result = compiler.compile_profile([])

        assert result.conversations_processed == 0
        assert len(result.pages_created) == 0
        assert provider.complete.call_count == 0

    def test_merge_failure_uses_first_batch(self):
        wiki = _make_wiki()
        provider = MagicMock()

        batch_response = MagicMock()
        batch_response.content = json.dumps({
            "job_role": "Engineer",
            "expertise_areas": ["Go"],
            "interests": [],
            "active_projects": [],
            "tools_and_tech": [],
            "decision_patterns": [],
            "communication_style": None,
            "key_people": [],
        })

        merge_fail = MagicMock()
        merge_fail.content = "NOT VALID JSON"

        # 2 batch calls succeed, merge returns bad JSON
        provider.complete.side_effect = [batch_response, batch_response, merge_fail]
        compiler = ProfileCompiler(provider, wiki)

        result = compiler.compile_profile(_make_conversations(6), batch_size=3)

        # Should fall back to first batch result
        assert len(result.pages_created) >= 1
        page = wiki.get_page("entities", "user-profile")
        assert page is not None
        assert "Engineer" in page


class TestProfileCompilerJSON:
    def test_parse_json_with_markdown_fences(self):
        text = '```json\n{"job_role": "Designer"}\n```'
        result = ProfileCompiler._parse_json_response(text)
        assert result == {"job_role": "Designer"}

    def test_parse_json_plain(self):
        text = '{"job_role": "Developer"}'
        result = ProfileCompiler._parse_json_response(text)
        assert result == {"job_role": "Developer"}

    def test_parse_json_invalid(self):
        result = ProfileCompiler._parse_json_response("not json at all")
        assert result is None

    def test_parse_json_array_rejected(self):
        result = ProfileCompiler._parse_json_response('[1, 2, 3]')
        assert result is None


class TestMemoryCompilerIntegration:
    def test_import_conversations_method(self):
        """Test MemoryCompiler.import_conversations delegates to ProfileCompiler."""
        from birkin.memory.compiler import MemoryCompiler
        from birkin.memory.event_store import EventStore

        tmpdir = tempfile.mkdtemp()
        wiki = WikiMemory(root=tmpdir)
        wiki.init()

        event_store = EventStore(db_path=":memory:")
        compiler = MemoryCompiler(event_store, wiki)

        provider = _make_fake_provider()
        result = compiler.import_conversations(_make_conversations(3), provider)

        assert result.events_processed == 3
        assert len(result.pages_created) >= 1
        event_store.close()
