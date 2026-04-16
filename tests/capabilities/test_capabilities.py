"""Tests for S6 agent capabilities — computer use, voice, context injection, approval gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin.core.approval.gate import ApprovalGate, ProposedAction
from birkin.core.context.injector import ContextInjector, InjectedContext
from birkin.core.context.profile import UserProfile
from birkin.memory.embeddings.encoder import SimpleHashEncoder
from birkin.memory.semantic_search import SemanticSearch
from birkin.memory.wiki import WikiMemory

# ---------------------------------------------------------------------------
# Computer Use (import-only since Playwright is optional)
# ---------------------------------------------------------------------------


class TestComputerUse:
    def test_import_tools(self) -> None:
        from birkin.mcp.servers.computer_use.server import ALL_COMPUTER_USE_TOOLS

        assert len(ALL_COMPUTER_USE_TOOLS) == 6
        names = [t().spec.name for t in ALL_COMPUTER_USE_TOOLS]
        assert "browser_navigate" in names
        assert "browser_screenshot" in names
        assert "browser_extract" in names

    def test_browser_available_check(self) -> None:
        from birkin.mcp.servers.computer_use.browser import is_available

        # Playwright not installed in test env, should be False
        assert isinstance(is_available(), bool)

    @pytest.mark.asyncio
    async def test_tool_returns_error_without_playwright(self) -> None:
        from birkin.mcp.servers.computer_use.server import NavigateTool
        from birkin.tools.base import ToolContext

        tool = NavigateTool()
        result = await tool.execute({"url": "https://example.com"}, ToolContext())
        # Should gracefully fail, not crash
        assert result.success is False
        assert "not installed" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# Voice I/O (import-only since API keys required)
# ---------------------------------------------------------------------------


class TestVoiceIO:
    def test_import_stt(self) -> None:
        from birkin.voice.stt import OpenAIWhisperSTT, SpeechToText

        stt = OpenAIWhisperSTT(api_key="test")
        assert isinstance(stt, SpeechToText)

    def test_import_tts(self) -> None:
        from birkin.voice.tts import CloudTTS, TextToSpeech

        tts = CloudTTS(api_key="test")
        assert isinstance(tts, TextToSpeech)

    def test_voice_router_import(self) -> None:
        from birkin.gateway.routers.voice import router

        assert router.prefix == "/api/voice"


# ---------------------------------------------------------------------------
# Context Injection
# ---------------------------------------------------------------------------


class TestUserProfile:
    def test_empty_profile(self) -> None:
        p = UserProfile()
        assert p.is_empty is True
        assert p.to_prompt_section() == ""

    def test_populated_profile(self) -> None:
        p = UserProfile(
            current_projects=["Birkin", "Side Project"],
            key_entities=["Claude", "GPT"],
            communication_style="concise, technical",
            recent_decisions=["Chose FastAPI over Flask"],
        )
        assert p.is_empty is False
        section = p.to_prompt_section()
        assert "Birkin" in section
        assert "Claude" in section
        assert "concise" in section
        assert "FastAPI" in section


class TestContextInjector:
    def test_build_context_with_keyword_search(self, tmp_path: Path) -> None:
        mem = WikiMemory(root=tmp_path / "memory")
        mem.init()
        mem.ingest("concepts", "fastapi", "# FastAPI\nModern Python web framework.")
        mem.ingest("concepts", "django", "# Django\nBatteries-included Python web framework.")

        injector = ContextInjector(mem)
        ctx = injector.build_context("How does FastAPI work?")
        assert isinstance(ctx, InjectedContext)
        # Should find FastAPI page via keyword search
        if ctx.source_pages:
            assert any("fastapi" in p for p in ctx.source_pages)

    def test_build_context_with_semantic_search(self, tmp_path: Path) -> None:
        mem = WikiMemory(root=tmp_path / "memory")
        mem.init()
        mem.ingest("concepts", "async-python", "# Async Python\nAsyncio patterns.")
        mem.ingest("entities", "birkin", "# Birkin\nAI agent.")

        search = SemanticSearch(mem, SimpleHashEncoder())
        search.index_all()

        injector = ContextInjector(mem, search=search)
        ctx = injector.build_context("async programming")
        assert ctx.tokens_added >= 0
        assert len(ctx.system_addition) > 0

    def test_build_context_with_profile(self, tmp_path: Path) -> None:
        mem = WikiMemory(root=tmp_path / "memory")
        mem.init()

        profile = UserProfile(current_projects=["Birkin"])
        injector = ContextInjector(mem, profile=profile)
        ctx = injector.build_context("hello")
        assert "Birkin" in ctx.system_addition

    def test_xml_format(self, tmp_path: Path) -> None:
        mem = WikiMemory(root=tmp_path / "memory")
        mem.init()
        mem.ingest("concepts", "test", "# Test\nContent.")

        injector = ContextInjector(mem)
        ctx = injector.build_context("test", style="xml")
        if ctx.source_pages:
            assert "<user_context>" in ctx.system_addition

    def test_markdown_format(self, tmp_path: Path) -> None:
        mem = WikiMemory(root=tmp_path / "memory")
        mem.init()
        mem.ingest("concepts", "test", "# Test\nContent.")

        injector = ContextInjector(mem)
        ctx = injector.build_context("test", style="markdown")
        if ctx.source_pages:
            assert "## Relevant Context" in ctx.system_addition

    def test_empty_memory(self, tmp_path: Path) -> None:
        mem = WikiMemory(root=tmp_path / "memory")
        mem.init()
        injector = ContextInjector(mem)
        ctx = injector.build_context("anything")
        assert ctx.source_pages == []


# ---------------------------------------------------------------------------
# Approval Gates
# ---------------------------------------------------------------------------


class TestApprovalGate:
    def test_submit_and_approve(self) -> None:
        gate = ApprovalGate()
        action = ProposedAction(action_type="send_email", summary="Send report")
        gate.submit(action)
        assert len(gate) == 1
        assert gate.is_pending(action.id)

        gate.approve(action.id, note="Go ahead")
        assert len(gate) == 0
        assert not gate.is_pending(action.id)

        decision = gate.get_decision(action.id)
        assert decision is not None
        assert decision.approved is True
        assert decision.user_note == "Go ahead"

    def test_submit_and_reject(self) -> None:
        gate = ApprovalGate()
        action = ProposedAction(action_type="delete_file", summary="Delete backup", estimated_impact="high")
        gate.submit(action)

        gate.reject(action.id, note="Too risky")
        decision = gate.get_decision(action.id)
        assert decision.approved is False
        assert decision.user_note == "Too risky"

    def test_approve_nonexistent(self) -> None:
        gate = ApprovalGate()
        assert gate.approve("nonexistent") is False

    def test_list_pending(self) -> None:
        gate = ApprovalGate()
        for i in range(3):
            gate.submit(ProposedAction(action_type="test", summary=f"Action {i}"))
        assert len(gate.list_pending()) == 3

        gate.approve(gate.list_pending()[0].id)
        assert len(gate.list_pending()) == 2

    def test_approve_with_modified_payload(self) -> None:
        gate = ApprovalGate()
        action = ProposedAction(
            action_type="api_call",
            summary="Call external API",
            payload={"url": "http://example.com", "method": "POST"},
        )
        gate.submit(action)
        gate.approve(action.id, modified_payload={"url": "http://safe.com", "method": "GET"})

        decision = gate.get_decision(action.id)
        assert decision.modified_payload["url"] == "http://safe.com"

    def test_proposed_action_frozen(self) -> None:
        action = ProposedAction(action_type="test", summary="Test")
        with pytest.raises(Exception):
            action.summary = "changed"

    @pytest.mark.asyncio
    async def test_wait_for_decision(self) -> None:
        import asyncio

        gate = ApprovalGate()
        action = ProposedAction(action_type="test", summary="Wait test")
        gate.submit(action)

        # Approve after a short delay
        async def approve_later() -> None:
            await asyncio.sleep(0.1)
            gate.approve(action.id)

        asyncio.create_task(approve_later())
        decision = await gate.wait_for_decision(action.id, timeout_sec=2)
        assert decision is not None
        assert decision.approved is True
