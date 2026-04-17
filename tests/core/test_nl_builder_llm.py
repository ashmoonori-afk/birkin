"""Tests for LLM-powered workflow builder."""

from __future__ import annotations

import json
from typing import Any

import pytest

from birkin.core.models import Message
from birkin.core.providers.base import (
    ModelCapabilities,
    Provider,
    ProviderResponse,
)
from birkin.core.workflow.nl_builder import build_workflow
from birkin.core.workflow.nl_builder_llm import (
    VALID_NODE_TYPES,
    LLMWorkflowBuilder,
    validate_node_types,
)

# ── Helpers ───────────────────────────────────────────────────────────


class FakeProvider(Provider):
    """Minimal provider that returns a pre-configured response."""

    def __init__(self, response_content: str) -> None:
        self._content = response_content

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(context_window=4096)

    def complete(self, messages: list[Message], **kwargs: Any) -> ProviderResponse:
        return ProviderResponse(content=self._content)

    async def acomplete(self, messages: list[Message], **kwargs: Any) -> ProviderResponse:
        return ProviderResponse(content=self._content)


VALID_GRAPH_JSON = json.dumps(
    {
        "name": "summarize-and-notify",
        "description": "Summarize a page and send to Telegram",
        "mode": "graph",
        "nodes": [
            {"id": "start", "type": "input", "config": {}},
            {"id": "fetch", "type": "web-search", "config": {}},
            {"id": "summarize", "type": "summarizer", "config": {}},
            {"id": "send", "type": "telegram-send", "config": {}},
        ],
        "edges": [
            {"from": "start", "to": "fetch"},
            {"from": "fetch", "to": "summarize"},
            {"from": "summarize", "to": "send"},
            {"from": "send", "to": "__end__"},
        ],
    }
)

KOREAN_GRAPH_JSON = json.dumps(
    {
        "name": "read-translate-email",
        "description": "파일을 읽고 번역한 뒤 이메일로 보내줘",
        "mode": "graph",
        "nodes": [
            {"id": "start", "type": "input", "config": {}},
            {"id": "read-file", "type": "file-read", "config": {}},
            {
                "id": "translate",
                "type": "translator",
                "config": {"target_language": "English"},
            },
            {"id": "send-email", "type": "email-send", "config": {}},
        ],
        "edges": [
            {"from": "start", "to": "read-file"},
            {"from": "read-file", "to": "translate"},
            {"from": "translate", "to": "send-email"},
            {"from": "send-email", "to": "__end__"},
        ],
    }
)

INVALID_NODE_GRAPH_JSON = json.dumps(
    {
        "name": "bad-workflow",
        "description": "invalid",
        "mode": "graph",
        "nodes": [
            {"id": "start", "type": "input", "config": {}},
            {"id": "bad", "type": "nonexistent-node-type", "config": {}},
        ],
        "edges": [{"from": "start", "to": "bad"}],
    }
)


# ── VALID_NODE_TYPES tests ────────────────────────────────────────────


def test_valid_node_types_matches_engine() -> None:
    """VALID_NODE_TYPES should contain all keys from WorkflowEngine._NODE_HANDLERS."""
    from birkin.core.workflow_engine import WorkflowEngine

    engine_types = set(WorkflowEngine._NODE_HANDLERS.keys())
    assert VALID_NODE_TYPES == engine_types


# ── validate_node_types tests ─────────────────────────────────────────


def test_validate_node_types_all_valid() -> None:
    graph = {"nodes": [{"type": "input"}, {"type": "llm"}, {"type": "notify"}]}
    assert validate_node_types(graph) == []


def test_validate_node_types_detects_invalid() -> None:
    graph = {"nodes": [{"type": "input"}, {"type": "magic-wand"}]}
    invalid = validate_node_types(graph)
    assert invalid == ["magic-wand"]


# ── LLMWorkflowBuilder tests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_builder_valid_english() -> None:
    """LLM returns valid JSON -- should produce a correct graph."""
    provider = FakeProvider(VALID_GRAPH_JSON)
    builder = LLMWorkflowBuilder(provider)
    graph = await builder.generate("Summarize a page and send to Telegram")

    assert graph["mode"] == "graph"
    assert len(graph["nodes"]) == 4
    assert len(graph["edges"]) == 4
    node_types = {n["type"] for n in graph["nodes"]}
    assert node_types <= VALID_NODE_TYPES | {"__end__"}


@pytest.mark.asyncio
async def test_llm_builder_valid_korean() -> None:
    """LLM returns valid Korean workflow graph."""
    provider = FakeProvider(KOREAN_GRAPH_JSON)
    builder = LLMWorkflowBuilder(provider)
    graph = await builder.generate("파일을 읽고 번역한 뒤 이메일로 보내줘")

    assert graph["name"] == "read-translate-email"
    node_types = [n["type"] for n in graph["nodes"]]
    assert "file-read" in node_types
    assert "translator" in node_types
    assert "email-send" in node_types


@pytest.mark.asyncio
async def test_llm_builder_invalid_json_falls_back() -> None:
    """Invalid JSON from LLM should trigger keyword fallback."""
    provider = FakeProvider("this is not json at all")
    builder = LLMWorkflowBuilder(provider)
    graph = await builder.generate("summarize and send email")

    # Fallback should still produce a valid graph structure
    assert "nodes" in graph
    assert "edges" in graph
    assert len(graph["nodes"]) > 0


@pytest.mark.asyncio
async def test_llm_builder_unknown_nodes_rejected() -> None:
    """Graph with invalid node types should fall back to keyword builder."""
    provider = FakeProvider(INVALID_NODE_GRAPH_JSON)
    builder = LLMWorkflowBuilder(provider)
    graph = await builder.generate("do something invalid")

    # Should have fallen back -- no 'nonexistent-node-type' in result
    for node in graph["nodes"]:
        assert node["type"] != "nonexistent-node-type"


@pytest.mark.asyncio
async def test_llm_builder_empty_response_falls_back() -> None:
    """Empty LLM response should trigger fallback."""
    provider = FakeProvider("")
    builder = LLMWorkflowBuilder(provider)
    graph = await builder.generate("summarize this")

    assert "nodes" in graph
    assert len(graph["nodes"]) > 0


@pytest.mark.asyncio
async def test_llm_builder_markdown_fenced_json() -> None:
    """LLM response wrapped in markdown code fences should be parsed."""
    fenced = f"```json\n{VALID_GRAPH_JSON}\n```"
    provider = FakeProvider(fenced)
    builder = LLMWorkflowBuilder(provider)
    graph = await builder.generate("summarize and notify")

    assert graph["mode"] == "graph"
    assert len(graph["nodes"]) == 4


# ── build_workflow facade tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_build_workflow_without_provider() -> None:
    """Without a provider, should use keyword builder."""
    graph = await build_workflow("summarize and send email")

    assert "nodes" in graph
    assert "edges" in graph
    assert len(graph["nodes"]) > 0


@pytest.mark.asyncio
async def test_build_workflow_with_provider() -> None:
    """With a provider, should use LLM builder."""
    provider = FakeProvider(VALID_GRAPH_JSON)
    graph = await build_workflow("Summarize a page and send to Telegram", provider=provider)

    assert graph["mode"] == "graph"
    assert len(graph["nodes"]) == 4


# ── WorkflowEngine.load() integration ────────────────────────────────


@pytest.mark.asyncio
async def test_generated_graph_loadable_by_engine() -> None:
    """Generated graph should be loadable by WorkflowEngine.load()."""
    provider = FakeProvider(VALID_GRAPH_JSON)
    builder = LLMWorkflowBuilder(provider)
    graph = await builder.generate("Summarize a page and send to Telegram")

    from birkin.core.workflow_engine import WorkflowEngine

    # WorkflowEngine requires a provider; use same fake
    engine = WorkflowEngine(provider)
    # load() should not raise
    engine.load(graph)

    # Verify engine parsed the nodes
    assert len(engine._node_map) == 4


@pytest.mark.asyncio
async def test_fallback_graph_loadable_by_engine() -> None:
    """Keyword-fallback graph should also be loadable by WorkflowEngine."""
    graph = await build_workflow("search the web and notify me")

    from birkin.core.workflow_engine import WorkflowEngine

    provider = FakeProvider("")
    engine = WorkflowEngine(provider)
    engine.load(graph)

    assert len(engine._node_map) > 0
