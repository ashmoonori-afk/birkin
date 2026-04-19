"""Wiring test — every registered node handler executes without crash.

Each test calls the handler directly with minimal input.
The goal is not to verify output correctness (that's in test_workflow_handlers
and test_new_nodes) but to confirm every handler is callable, handles empty/minimal
input gracefully, and returns a string.
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from birkin.core.providers.base import ProviderResponse, TokenUsage
from birkin.core.workflow_engine import WorkflowEngine


def _engine(llm_reply: str = "ok", wiki=None) -> WorkflowEngine:
    provider = MagicMock()
    provider.acomplete = AsyncMock(
        return_value=ProviderResponse(
            content=llm_reply,
            usage=TokenUsage(prompt_tokens=5, completion_tokens=5),
        )
    )
    return WorkflowEngine(provider=provider, wiki_memory=wiki)


def _n(ntype: str, **config) -> dict:
    return {"id": f"test-{ntype}", "type": ntype, "config": config}


# ---------------------------------------------------------------------------
# Passthrough nodes (input, output, webhook-trigger, cron-trigger)
# ---------------------------------------------------------------------------


class TestPassthroughNodes:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("ntype", ["input", "output", "webhook-trigger", "cron-trigger"])
    async def test_passthrough(self, ntype):
        e = _engine()
        result = await e._execute_node(_n(ntype), "hello")
        assert result == "hello"


# ---------------------------------------------------------------------------
# LLM-based nodes
# ---------------------------------------------------------------------------


class TestLLMNodes:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "ntype",
        ["llm", "llm-stream", "classifier", "embedder", "summarizer", "translator", "knowledge-extract", "switch"],
    )
    async def test_llm_node(self, ntype):
        e = _engine("generated")
        result = await e._execute_node(_n(ntype), "test input")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_condition(self):
        e = _engine("YES")
        result = await e._execute_node(_n("condition"), "check this")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_guardrail(self):
        e = _engine("SAFE")
        result = await e._execute_node(_n("guardrail"), "text")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_validator(self):
        e = _engine("VALID")
        result = await e._execute_node(_n("validator"), "data")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_code_review(self):
        e = _engine("no issues")
        result = await e._execute_node(_n("code-review"), "def foo(): pass")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_human_review(self):
        e = _engine()
        result = await e._execute_node(_n("human-review"), "review this")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Data transformation nodes
# ---------------------------------------------------------------------------


class TestDataNodes:
    @pytest.mark.asyncio
    async def test_csv_parse(self):
        e = _engine()
        csv = "name,age\nAlice,30\nBob,25"
        result = await e._execute_node(_n("csv-parse", format="json"), csv)
        assert "Alice" in result

    @pytest.mark.asyncio
    async def test_csv_parse_empty(self):
        e = _engine()
        result = await e._execute_node(_n("csv-parse"), "")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_json_transform(self):
        e = _engine()
        result = await e._execute_node(_n("json-transform", expression="name"), '{"name": "test"}')
        assert "test" in result

    @pytest.mark.asyncio
    async def test_json_transform_invalid(self):
        e = _engine()
        result = await e._execute_node(_n("json-transform"), "not json")
        assert "error" in result.lower() or "parse" in result.lower()

    @pytest.mark.asyncio
    async def test_data_format_json(self):
        e = _engine()
        result = await e._execute_node(_n("data-format", to="json"), "name,v\na,1")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_data_format_markdown(self):
        e = _engine()
        result = await e._execute_node(_n("data-format", to="markdown"), '[{"a":1}]')
        assert "|" in result

    @pytest.mark.asyncio
    async def test_html_parse_strip(self):
        e = _engine()
        # No selector → strip all tags
        result = await e._execute_node(_n("html-parse", selector=""), "<p>Hello <b>world</b></p>")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_html_parse_links(self):
        e = _engine()
        html = '<a href="https://x.com">X</a><a href="https://y.com">Y</a>'
        result = await e._execute_node(_n("html-parse", selector="a", attribute="href"), html)
        assert "https://x.com" in result

    @pytest.mark.asyncio
    async def test_prompt_template(self):
        e = _engine()
        result = await e._execute_node(_n("prompt-template", template="Say: {input}"), "hi")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Control flow nodes
# ---------------------------------------------------------------------------


class TestControlFlow:
    @pytest.mark.asyncio
    async def test_loop(self):
        e = _engine("done")
        result = await e._execute_node(_n("loop", max=2), "loop input")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_delay(self):
        e = _engine()
        result = await e._execute_node(_n("delay", seconds=0), "pass")
        assert result == "pass"

    @pytest.mark.asyncio
    async def test_for_each(self):
        e = _engine()
        result = await e._execute_node(_n("for-each"), "a\nb\nc")
        assert "a" in result

    @pytest.mark.asyncio
    async def test_try_catch(self):
        e = _engine()
        result = await e._execute_node(_n("try-catch"), "input")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_merge(self):
        e = _engine()
        e._merge_inputs = {}  # initialize merge state
        result = await e._execute_node(_n("merge"), "data")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_parallel(self):
        e = _engine()
        result = await e._execute_node(_n("parallel"), "data")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Time nodes
# ---------------------------------------------------------------------------


class TestTimeNodes:
    @pytest.mark.asyncio
    async def test_datetime_now(self):
        e = _engine()
        result = await e._execute_node(_n("datetime", operation="now"), "")
        assert len(result) >= 10  # at least YYYY-MM-DD

    @pytest.mark.asyncio
    async def test_datetime_add(self):
        e = _engine()
        result = await e._execute_node(_n("datetime", operation="add", days=1), "")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_rate_limit(self):
        e = _engine()
        result = await e._execute_node(_n("rate-limit", calls_per_minute=100), "pass")
        assert result == "pass"


# ---------------------------------------------------------------------------
# Communication nodes (test error paths — no real webhooks)
# ---------------------------------------------------------------------------


class TestCommNodes:
    @pytest.mark.asyncio
    async def test_slack_no_url(self):
        e = _engine()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SLACK_WEBHOOK_URL", None)
            result = await e._execute_node(_n("slack-send"), "msg")
        assert "not configured" in result.lower() or "webhook" in result.lower()

    @pytest.mark.asyncio
    async def test_discord_no_url(self):
        e = _engine()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISCORD_WEBHOOK_URL", None)
            result = await e._execute_node(_n("discord-send"), "msg")
        assert "not configured" in result.lower() or "webhook" in result.lower()

    @pytest.mark.asyncio
    async def test_sms_no_config(self):
        e = _engine()
        result = await e._execute_node(_n("sms-send"), "msg")
        assert "not configured" in result.lower() or "twilio" in result.lower()

    @pytest.mark.asyncio
    async def test_webhook_no_url(self):
        e = _engine()
        result = await e._execute_node(_n("webhook-send"), "msg")
        assert "requires" in result.lower() or "url" in result.lower()

    @pytest.mark.asyncio
    async def test_email_read_no_config(self):
        e = _engine()
        result = await e._execute_node(_n("email-read"), "")
        assert "not configured" in result.lower() or "imap" in result.lower()

    @pytest.mark.asyncio
    async def test_email_send(self):
        e = _engine()
        result = await e._execute_node(_n("email-send"), "body text")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_telegram_send(self):
        e = _engine()
        result = await e._execute_node(_n("telegram-send"), "msg")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_notify(self):
        e = _engine()
        result = await e._execute_node(_n("notify"), "alert")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Media nodes (test missing-dependency paths)
# ---------------------------------------------------------------------------


class TestMediaNodes:
    @pytest.mark.asyncio
    async def test_image_resize_no_pillow(self):
        e = _engine()
        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            result = await e._execute_node(_n("image-resize", path="/nonexistent"), "")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_image_generate_no_key(self):
        e = _engine()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            result = await e._execute_node(_n("image-generate"), "a cat")
        assert "api_key" in result.lower() or "openai" in result.lower() or "failed" in result.lower()

    @pytest.mark.asyncio
    async def test_vision_no_key(self):
        e = _engine()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            result = await e._execute_node(_n("vision-analyze", path="/none"), "")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_audio_transcribe_no_key(self):
        e = _engine()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            result = await e._execute_node(_n("audio-transcribe", path="/none"), "")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_pdf_extract_no_pymupdf(self):
        e = _engine()
        result = await e._execute_node(_n("pdf-extract", path="/none"), "")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Database nodes
# ---------------------------------------------------------------------------


class TestDBNodes:
    @pytest.mark.asyncio
    async def test_db_query(self):
        e = _engine()
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db = f.name
        try:
            import sqlite3

            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
            conn.execute("INSERT INTO t VALUES (1, 'a')")
            conn.commit()
            conn.close()
            result = await e._execute_node(_n("db-query", db=db, query="SELECT * FROM t"), "")
            assert "a" in result
        finally:
            os.unlink(db)

    @pytest.mark.asyncio
    async def test_db_query_blocks_drop(self):
        e = _engine()
        result = await e._execute_node(_n("db-query", query="DROP TABLE users"), "")
        assert "select" in result.lower() or "block" in result.lower() or "not allowed" in result.lower()

    @pytest.mark.asyncio
    async def test_db_write(self, tmp_path):
        e = _engine()
        db = str(tmp_path / "write.db")
        import sqlite3

        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.commit()
        conn.close()
        result = await e._execute_node(_n("db-write", db=db, query="INSERT INTO t VALUES (1)"), "")
        assert "1" in result or "ok" in result.lower()

    @pytest.mark.asyncio
    async def test_cloud_storage_no_cli(self):
        e = _engine()
        result = await e._execute_node(_n("cloud-storage", provider="s3", bucket="b", key="k", operation="list"), "")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Web nodes (error paths)
# ---------------------------------------------------------------------------


class TestWebNodes:
    @pytest.mark.asyncio
    async def test_rss_no_url(self):
        e = _engine()
        result = await e._execute_node(_n("rss-fetch"), "")
        assert "requires" in result.lower() or "url" in result.lower()

    @pytest.mark.asyncio
    async def test_web_scrape_no_url(self):
        e = _engine()
        result = await e._execute_node(_n("web-scrape"), "")
        assert "requires" in result.lower() or "url" in result.lower()

    @pytest.mark.asyncio
    async def test_web_search(self):
        e = _engine()
        result = await e._execute_node(_n("web-search"), "test query")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_hn_fetch(self):
        e = _engine()
        result = await e._execute_node(_n("hn-fetch"), "")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Calendar & task nodes
# ---------------------------------------------------------------------------


class TestCalendarTaskNodes:
    @pytest.mark.asyncio
    async def test_calendar_event(self):
        e = _engine()
        result = await e._execute_node(
            _n("calendar-event", operation="create", title="Meeting", start="2026-04-20T10:00:00"), ""
        )
        assert "VCALENDAR" in result

    @pytest.mark.asyncio
    async def test_task_create_no_key(self):
        e = _engine()
        result = await e._execute_node(_n("task-create", provider="todoist"), "Do this")
        assert "todoist" in result.lower() or "api_key" in result.lower() or "not" in result.lower()


# ---------------------------------------------------------------------------
# Document generation (dependency check)
# ---------------------------------------------------------------------------


class TestDocNodes:
    @pytest.mark.asyncio
    async def test_pdf_generate(self):
        e = _engine()
        result = await e._execute_node(_n("pdf-generate"), "# Title\n\nHello world")
        assert isinstance(result, str)  # either success or "requires reportlab"

    @pytest.mark.asyncio
    async def test_spreadsheet_write(self):
        e = _engine()
        result = await e._execute_node(_n("spreadsheet-write"), '[{"a":1,"b":2}]')
        assert isinstance(result, str)  # either success or "requires openpyxl"


# ---------------------------------------------------------------------------
# Security node
# ---------------------------------------------------------------------------


class TestSecurityNode:
    @pytest.mark.asyncio
    async def test_secret_inject(self):
        e = _engine()
        # The handler's regex fallback replaces {{VAR}} with os.environ[VAR]
        os.environ["API_KEY"] = "s3cr3t"
        try:
            result = await e._execute_node(_n("secret-inject"), "token={{API_KEY}}")
            assert "s3cr3t" in result
        finally:
            os.environ.pop("API_KEY", None)

    @pytest.mark.asyncio
    async def test_secret_inject_no_secrets(self):
        e = _engine()
        result = await e._execute_node(_n("secret-inject"), "passthrough")
        assert result == "passthrough"


# ---------------------------------------------------------------------------
# Memory nodes
# ---------------------------------------------------------------------------


class TestMemoryNodes:
    @pytest.mark.asyncio
    async def test_memory_search_no_wiki(self):
        e = _engine()
        result = await e._execute_node(_n("memory-search"), "query")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_memory_write_no_wiki(self):
        e = _engine()
        result = await e._execute_node(_n("memory-write"), "content")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_context_inject_no_wiki(self):
        e = _engine()
        result = await e._execute_node(_n("context-inject"), "text")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Tool nodes
# ---------------------------------------------------------------------------


class TestToolNodes:
    @pytest.mark.asyncio
    async def test_tool_dispatch(self):
        e = _engine()
        result = await e._execute_node(_n("tool-dispatch", tool="nonexistent"), "data")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_shell(self):
        e = _engine()
        result = await e._execute_node(_n("shell"), "echo hello")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_test_runner(self):
        e = _engine("all pass")
        result = await e._execute_node(_n("test-runner"), "code")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_file_read(self):
        e = _engine()
        result = await e._execute_node(_n("file-read"), "/nonexistent_file")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_api_call(self):
        e = _engine()
        result = await e._execute_node(_n("api-call"), "https://example.com")
        assert isinstance(result, str)
