"""E2E tests for the HackerNews Daily Digest → Telegram workflow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from birkin.core.models import Message
from birkin.core.providers.base import ProviderResponse
from birkin.core.workflow_engine import WorkflowEngine
from birkin.gateway.workflows import load_workflows

# ── Fixtures ──────────────────────────────────────────────────────────

FAKE_STORY_IDS = [100, 200, 300]

FAKE_STORIES = {
    100: {"title": "Show HN: A cool project", "score": 150, "url": "https://example.com/a"},
    200: {"title": "Ask HN: Best books?", "score": 95, "url": "https://example.com/b"},
    300: {"title": "Rust vs Go 2026", "score": 210, "url": "https://example.com/c"},
}

HN_WORKFLOW = {
    "id": "hackernews-daily-telegram",
    "name": "HackerNews Daily Digest",
    "description": "Fetch top HN stories, summarize, send to Telegram",
    "nodes": [
        {"id": "n1", "type": "input", "x": 60, "y": 200, "config": {}},
        {"id": "n2", "type": "hn-fetch", "x": 240, "y": 200, "config": {"count": 3}},
        {"id": "n3", "type": "summarizer", "x": 420, "y": 200, "config": {}},
        {"id": "n4", "type": "telegram-send", "x": 600, "y": 200, "config": {"chat_id": "12345"}},
        {"id": "n5", "type": "output", "x": 780, "y": 200, "config": {}},
    ],
    "edges": [
        {"from": "n1", "to": "n2"},
        {"from": "n2", "to": "n3"},
        {"from": "n3", "to": "n4"},
        {"from": "n4", "to": "n5"},
    ],
}


def _make_provider() -> MagicMock:
    provider = MagicMock()
    provider.acomplete = AsyncMock(return_value=ProviderResponse(content="Summary of top HN stories"))
    return provider


def _make_httpx_response(json_data: object, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("GET", "https://fake.test"),
    )


# ── Tests ─────────────────────────────────────────────────────────────


class TestWorkflowLoads:
    """Verify the workflow JSON loads without errors."""

    def test_load_workflow_definition(self) -> None:
        provider = _make_provider()
        engine = WorkflowEngine(provider)
        engine.load(HN_WORKFLOW)
        # No exception means success; verify node map was populated
        assert len(engine._node_map) == 5
        assert "n2" in engine._node_map
        assert engine._node_map["n2"]["type"] == "hn-fetch"

    def test_hn_workflow_in_samples(self) -> None:
        result = load_workflows()
        sample_ids = [s["id"] for s in result["samples"]]
        assert "hackernews-daily-telegram" in sample_ids

    def test_samples_count_is_eleven(self) -> None:
        result = load_workflows()
        assert len(result["samples"]) == 11


class TestHnFetchHandler:
    """Test _handle_hn_fetch with mocked httpx."""

    @pytest.mark.asyncio
    async def test_fetches_and_formats_stories(self) -> None:
        provider = _make_provider()
        engine = WorkflowEngine(provider)

        node = {"id": "n2", "type": "hn-fetch", "config": {"count": 3}}

        async def _mock_get(url: str) -> httpx.Response:
            if "topstories" in url:
                return _make_httpx_response(FAKE_STORY_IDS)
            for sid, story in FAKE_STORIES.items():
                if str(sid) in url:
                    return _make_httpx_response(story)
            return _make_httpx_response({}, 404)

        mock_client = AsyncMock()
        mock_client.get = _mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await engine._handle_hn_fetch(node, "")

        assert "Show HN: A cool project" in result
        assert "150 pts" in result
        assert "Ask HN: Best books?" in result
        assert "Rust vs Go 2026" in result
        # Check numbered format
        assert result.startswith("1. ")
        assert "2. " in result
        assert "3. " in result

    @pytest.mark.asyncio
    async def test_handles_http_error(self) -> None:
        provider = _make_provider()
        engine = WorkflowEngine(provider)
        node = {"id": "n2", "type": "hn-fetch", "config": {"count": 5}}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await engine._handle_hn_fetch(node, "")

        assert "HN fetch failed" in result

    @pytest.mark.asyncio
    async def test_respects_count_config(self) -> None:
        provider = _make_provider()
        engine = WorkflowEngine(provider)
        node = {"id": "n2", "type": "hn-fetch", "config": {"count": 2}}

        all_ids = [100, 200, 300, 400, 500]

        async def _mock_get(url: str) -> httpx.Response:
            if "topstories" in url:
                return _make_httpx_response(all_ids)
            return _make_httpx_response({"title": "Story", "score": 10, "url": "https://example.com"})

        mock_client = AsyncMock()
        mock_client.get = _mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await engine._handle_hn_fetch(node, "")

        # Should only have 2 stories (count=2)
        lines = [line for line in result.strip().split("\n") if line.strip()]
        assert len(lines) == 2


class TestFullWorkflowRun:
    """E2E: mock all externals and run the full workflow."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self) -> None:
        provider = _make_provider()
        engine = WorkflowEngine(provider)
        engine.load(HN_WORKFLOW)

        # Mock httpx for hn-fetch
        async def _mock_get(url: str) -> httpx.Response:
            if "topstories" in url:
                return _make_httpx_response(FAKE_STORY_IDS)
            for sid, story in FAKE_STORIES.items():
                if str(sid) in url:
                    return _make_httpx_response(story)
            return _make_httpx_response({}, 404)

        mock_client = AsyncMock()
        mock_client.get = _mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        # Mock telegram adapter
        mock_adapter = AsyncMock()
        mock_adapter.send_message = AsyncMock()

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch(
                "birkin.gateway.deps.get_telegram_adapter",
                return_value=mock_adapter,
            ),
        ):
            result = await engine.run("fetch news")

        # Provider.acomplete called by summarizer node
        provider.acomplete.assert_called_once()
        call_args = provider.acomplete.call_args[0][0]
        # The summarizer should have received text containing HN stories
        assert isinstance(call_args, list)
        assert len(call_args) == 1
        assert isinstance(call_args[0], Message)
        assert "Show HN: A cool project" in call_args[0].content

        # Telegram adapter should have been called with the summary
        mock_adapter.send_message.assert_called_once()
        call_kwargs = mock_adapter.send_message.call_args
        assert call_kwargs.kwargs.get("chat_id") == 12345
        assert "Summary" in call_kwargs.kwargs.get("text", "")

        # Final output should be the telegram confirmation
        assert "Sent to Telegram" in result
