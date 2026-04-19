"""Unit tests for extended workflow engine node handlers.

Tests cover: csv-parse, json-transform, data-format, datetime, html-parse,
switch, for-each, rate-limit, db-query, db-write, secret-inject,
calendar-event, slack-send, web-scrape, try-catch, pdf-extract.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from birkin.core.providers.base import ProviderResponse, TokenUsage
from birkin.core.workflow_engine import WorkflowEngine

# ── Helpers ──


def _make_engine(llm_reply: str = "ok", wiki: object | None = None) -> WorkflowEngine:
    """Create a WorkflowEngine with a mocked provider."""
    provider = MagicMock()
    provider.acomplete = AsyncMock(
        return_value=ProviderResponse(
            content=llm_reply,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
        )
    )
    return WorkflowEngine(provider=provider, wiki_memory=wiki)


def _node(ntype: str, **config: object) -> dict:
    return {"id": "t1", "type": ntype, "config": config}


# ── csv-parse ──


class TestCsvParse:
    @pytest.mark.asyncio
    async def test_csv_parse_json(self):
        """Valid CSV parsed with format=json returns valid JSON output."""
        engine = _make_engine()
        csv_input = "name,age\nAlice,30\nBob,25"
        result = await engine._handle_csv_parse(_node("csv-parse", format="json"), csv_input)
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0]["name"] == "Alice"
        assert parsed[1]["age"] == "25"

    @pytest.mark.asyncio
    async def test_csv_parse_empty(self):
        """Empty CSV input returns empty JSON array or error message."""
        engine = _make_engine()
        result = await engine._handle_csv_parse(_node("csv-parse", format="json"), "")
        # DictReader on empty string produces no rows → "[]"
        parsed = json.loads(result)
        assert parsed == []

    @pytest.mark.asyncio
    async def test_csv_parse_markdown(self):
        """CSV parsed with format=markdown returns table with pipe characters."""
        engine = _make_engine()
        csv_input = "col1,col2\nval1,val2"
        result = await engine._handle_csv_parse(_node("csv-parse", format="markdown"), csv_input)
        assert "|" in result
        assert "col1" in result
        assert "val1" in result


# ── json-transform ──


class TestJsonTransform:
    @pytest.mark.asyncio
    async def test_json_transform_extract(self):
        """Extract a field from JSON object using expression config."""
        engine = _make_engine()
        json_input = json.dumps({"name": "Alice", "age": 30})
        result = await engine._handle_json_transform(_node("json-transform", expression="name"), json_input)
        # Handler returns json.dumps of the extracted value
        assert json.loads(result) == "Alice"

    @pytest.mark.asyncio
    async def test_json_transform_invalid(self):
        """Invalid JSON input returns an error message."""
        engine = _make_engine()
        result = await engine._handle_json_transform(_node("json-transform", expression="name"), "not json")
        assert "error" in result.lower()


# ── data-format ──


class TestDataFormat:
    @pytest.mark.asyncio
    async def test_data_format_csv_to_json(self):
        """CSV input converted to JSON array."""
        engine = _make_engine()
        csv_input = "x,y\n1,2\n3,4"
        result = await engine._handle_data_format(_node("data-format", to="json"), csv_input)
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 2


# ── datetime ──


class TestDatetime:
    @pytest.mark.asyncio
    async def test_datetime_now(self):
        """operation=now returns non-empty current date string."""
        engine = _make_engine()
        result = await engine._handle_datetime(_node("datetime", operation="now"), "")
        assert result
        assert len(result) >= 10  # At least YYYY-MM-DD

    @pytest.mark.asyncio
    async def test_datetime_add(self):
        """operation=add with days=1 returns a future date."""
        engine = _make_engine()
        result = await engine._handle_datetime(_node("datetime", operation="add", days=1), "2025-01-01")
        assert "2025-01-02" in result


# ── html-parse ──


class TestHtmlParse:
    @pytest.mark.asyncio
    async def test_html_parse_text(self):
        """HTML with <a> tags extracts href values by default."""
        engine = _make_engine()
        html_input = '<p>Hello <a href="http://example.com">World</a></p>'
        result = await engine._handle_html_parse(_node("html-parse"), html_input)
        # Default: tag=a, attribute=href → extracts href values
        assert "http://example.com" in result

    @pytest.mark.asyncio
    async def test_html_parse_links(self):
        """Extract href attributes from multiple anchor tags."""
        engine = _make_engine()
        html_input = '<a href="https://example.com">Link1</a><a href="https://test.org">Link2</a>'
        result = await engine._handle_html_parse(_node("html-parse", tag="a", attribute="href"), html_input)
        assert "https://example.com" in result
        assert "https://test.org" in result


# ── switch ──


class TestSwitch:
    @pytest.mark.asyncio
    async def test_switch_routes(self):
        """Switch node routes based on LLM classification."""
        engine = _make_engine("urgent")
        result = await engine._handle_switch(
            _node("switch", cases={"urgent": "handle_urgent", "normal": "handle_normal"}),
            "Server is on fire!",
        )
        assert result == "urgent"


# ── for-each ──


class TestForEach:
    @pytest.mark.asyncio
    async def test_for_each_lines(self):
        """for-each splits input by lines and joins results."""
        engine = _make_engine()
        # Without children config, each item passes through as-is
        result = await engine._handle_for_each(_node("for-each"), "a\nb\nc")
        parts = result.split("\n")
        assert len(parts) == 3
        assert parts[0] == "a"
        assert parts[1] == "b"
        assert parts[2] == "c"


# ── rate-limit ──


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_rate_limit_passthrough(self):
        """Under rate limit, input passes through unchanged."""
        engine = _make_engine()
        result = await engine._handle_rate_limit(_node("rate-limit", calls_per_minute=100), "hello")
        assert result == "hello"


# ── db-query / db-write ──


class TestDbQuery:
    @pytest.mark.asyncio
    async def test_db_query_select(self):
        """SELECT query on a real temp SQLite DB returns JSON result."""
        # Create a temp database file with test data
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE users (id INTEGER, name TEXT)")
            conn.execute("INSERT INTO users VALUES (1, 'Alice')")
            conn.execute("INSERT INTO users VALUES (2, 'Bob')")
            conn.commit()
            conn.close()

            engine = _make_engine()
            result = await engine._handle_db_query(
                _node("db-query", db=db_path),
                "SELECT * FROM users",
            )
            parsed = json.loads(result)
            assert len(parsed) == 2
            assert parsed[0]["name"] == "Alice"
        finally:
            os.unlink(db_path)

    @pytest.mark.asyncio
    async def test_db_query_blocks_drop(self):
        """DROP TABLE statement is blocked for safety."""
        engine = _make_engine()
        result = await engine._handle_db_query(
            _node("db-query", db=":memory:"),
            "DROP TABLE users",
        )
        assert "only select" in result.lower() or "not allowed" in result.lower()


class TestDbWrite:
    @pytest.mark.asyncio
    async def test_db_write_insert(self):
        """INSERT statement reports rows affected."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE items (id INTEGER, val TEXT)")
            conn.commit()
            conn.close()

            engine = _make_engine()
            result = await engine._handle_db_write(
                _node("db-write", db=db_path),
                "INSERT INTO items VALUES (1, 'test')",
            )
            assert "1" in result
            assert "row" in result.lower() or "affected" in result.lower()
        finally:
            os.unlink(db_path)


# ── secret-inject ──


class TestSecretInject:
    @pytest.mark.asyncio
    async def test_secret_inject(self):
        """Environment variable placeholder replaced with secret value."""
        engine = _make_engine()
        with patch.dict(os.environ, {"TEST_KEY": "secret_value"}):
            result = await engine._handle_secret_inject(
                _node("secret-inject", secrets={"API_KEY": "TEST_KEY"}),
                "Authorization: Bearer {{API_KEY}}",
            )
        assert "secret_value" in result
        assert "{{API_KEY}}" not in result


# ── calendar-event ──


class TestCalendarEvent:
    @pytest.mark.asyncio
    async def test_calendar_event(self):
        """operation=create with start returns valid VCALENDAR output."""
        engine = _make_engine()
        result = await engine._handle_calendar_event(
            _node(
                "calendar-event",
                summary="Meeting",
                dtstart="20250601T100000",
                dtend="20250601T110000",
            ),
            "",
        )
        assert "BEGIN:VCALENDAR" in result
        assert "BEGIN:VEVENT" in result
        assert "Meeting" in result


# ── slack-send ──


class TestSlackSend:
    @pytest.mark.asyncio
    async def test_slack_send_no_url(self):
        """No webhook URL configured returns an error message."""
        engine = _make_engine()
        # Ensure no SLACK_WEBHOOK_URL env var
        with patch.dict(os.environ, {}, clear=True):
            result = await engine._handle_slack_send(_node("slack-send"), "Hello Slack")
        assert "webhook" in result.lower() or "url" in result.lower() or "config" in result.lower()


# ── web-scrape ──


class TestWebScrape:
    @pytest.mark.asyncio
    async def test_web_scrape_no_url(self):
        """Empty URL returns an error message."""
        engine = _make_engine()
        result = await engine._handle_web_scrape(_node("web-scrape", url=""), "")
        assert "error" in result.lower() or "scrape" in result.lower()


# ── try-catch ──


class TestTryCatch:
    @pytest.mark.asyncio
    async def test_try_catch_success(self):
        """Subgraph succeeds, try-catch returns the result."""
        engine = _make_engine("success result")
        # Set up a child node in the engine's node_map
        engine._node_map = {"child1": {"id": "child1", "type": "llm", "config": {}}}
        result = await engine._handle_try_catch(
            _node("try-catch", children=["child1"]),
            "input data",
        )
        assert "success result" in result


# ── pdf-extract ──


class TestPdfExtract:
    @pytest.mark.asyncio
    async def test_pdf_extract_no_pymupdf(self):
        """When pymupdf is not installed, returns install message."""
        engine = _make_engine()
        # Simulate fitz not being importable

        original = sys.modules.get("fitz")
        sys.modules["fitz"] = None  # type: ignore[assignment]
        try:
            result = await engine._handle_pdf_extract(_node("pdf-extract"), "/tmp/test.pdf")
        finally:
            if original is not None:
                sys.modules["fitz"] = original
            else:
                sys.modules.pop("fitz", None)
        assert "pymupdf" in result.lower() or "install" in result.lower() or "fitz" in result.lower()
