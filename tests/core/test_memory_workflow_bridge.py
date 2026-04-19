"""Tests for Memory <-> Workflow Bridge (Improvement #3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from birkin.core.providers.base import ProviderResponse, TokenUsage
from birkin.core.workflow_engine import WorkflowEngine

# -- helpers ----------------------------------------------------------------


def _make_engine(llm_reply: str = "ok", wiki=None) -> WorkflowEngine:
    provider = MagicMock()
    provider.acomplete = AsyncMock(
        return_value=ProviderResponse(content=llm_reply, usage=TokenUsage(prompt_tokens=10, completion_tokens=5))
    )
    return WorkflowEngine(provider=provider, wiki_memory=wiki)


def _simple_workflow():
    return {
        "nodes": [
            {"id": "in", "type": "input", "config": {}},
            {"id": "llm1", "type": "llm", "config": {}},
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [
            {"from": "in", "to": "llm1"},
            {"from": "llm1", "to": "out"},
        ],
    }


# -- 3a: Memory → Workflow -------------------------------------------------


class TestMemoryInjection:
    @pytest.mark.asyncio
    async def test_llm_node_injects_memory_context(self):
        wiki = MagicMock()
        wiki.build_context.return_value = "User likes Python."

        engine = _make_engine("Generated output", wiki=wiki)
        engine.load(_simple_workflow())
        await engine.run("Hello")

        wiki.build_context.assert_called_once_with(max_pages=3)
        # The provider should have received memory context in the prompt
        call_args = engine._provider.acomplete.call_args
        messages = call_args[0][0]
        user_msg = next(m for m in messages if m.role == "user")
        assert "[Memory Context]" in user_msg.content
        assert "User likes Python." in user_msg.content

    @pytest.mark.asyncio
    async def test_memory_injection_opt_out(self):
        wiki = MagicMock()
        wiki.build_context.return_value = "Some context"

        wf = {
            "nodes": [
                {"id": "in", "type": "input", "config": {}},
                {"id": "llm1", "type": "llm", "config": {"inject_memory": False}},
                {"id": "out", "type": "output", "config": {}},
            ],
            "edges": [
                {"from": "in", "to": "llm1"},
                {"from": "llm1", "to": "out"},
            ],
        }
        engine = _make_engine("ok", wiki=wiki)
        engine.load(wf)
        await engine.run("test")

        wiki.build_context.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_wiki_no_injection(self):
        engine = _make_engine("ok", wiki=None)
        engine.load(_simple_workflow())
        result = await engine.run("test")
        assert result == "ok"


# -- 3b: Workflow → Memory -------------------------------------------------


class TestWorkflowResultCapture:
    @pytest.mark.asyncio
    async def test_workflow_result_saved_to_wiki(self):
        wiki = MagicMock()
        wiki.build_context.return_value = ""

        engine = _make_engine("Analysis complete", wiki=wiki)
        engine.load(_simple_workflow())
        await engine.run("Analyze this")

        wiki.ingest.assert_called_once()
        call_args = wiki.ingest.call_args
        assert call_args[0][0] == "workflows"  # category
        assert call_args[0][1].startswith("wf-")  # slug
        assert call_args[0][2] == "Analysis complete"  # content

    @pytest.mark.asyncio
    async def test_no_save_when_output_unchanged(self):
        """If workflow produces no change (output == input), skip save."""
        wiki = MagicMock()
        wiki.build_context.return_value = ""

        # Make LLM return the same as input (passthrough scenario)
        provider = MagicMock()
        provider.acomplete = AsyncMock(
            return_value=ProviderResponse(content="test input", usage=TokenUsage(prompt_tokens=1, completion_tokens=1))
        )
        engine = WorkflowEngine(provider=provider, wiki_memory=wiki)

        # Workflow with just input -> output (no LLM)
        wf = {
            "nodes": [
                {"id": "in", "type": "input", "config": {}},
                {"id": "out", "type": "output", "config": {}},
            ],
            "edges": [{"from": "in", "to": "out"}],
        }
        engine.load(wf)
        await engine.run("test input")

        wiki.ingest.assert_not_called()
