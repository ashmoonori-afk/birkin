"""Tests for birkin.observability — trace, logger, storage."""

from __future__ import annotations

from pathlib import Path

from birkin.observability.logger import StructuredLogger
from birkin.observability.storage import TraceStorage
from birkin.observability.trace import Span, Trace


class TestTraceModel:
    def test_total_tokens(self) -> None:
        trace = Trace(
            trace_id="t1",
            spans=[
                Span(span_id="s1", name="a", tokens_in=100, tokens_out=50),
                Span(span_id="s2", name="b", tokens_in=200, tokens_out=100),
            ],
        )
        assert trace.total_tokens == 450

    def test_total_latency(self) -> None:
        trace = Trace(
            trace_id="t1",
            spans=[
                Span(span_id="s1", name="a", latency_ms=100),
                Span(span_id="s2", name="b", latency_ms=200),
            ],
        )
        assert trace.total_latency_ms == 300

    def test_has_errors(self) -> None:
        trace = Trace(
            trace_id="t1",
            spans=[
                Span(span_id="s1", name="ok", status="ok"),
            ],
        )
        assert trace.has_errors is False

        trace2 = Trace(
            trace_id="t2",
            spans=[
                Span(span_id="s1", name="ok", status="ok"),
                Span(span_id="s2", name="err", status="error"),
            ],
        )
        assert trace2.has_errors is True

    def test_empty_trace(self) -> None:
        trace = Trace(trace_id="t1")
        assert trace.total_tokens == 0
        assert trace.total_latency_ms == 0
        assert trace.has_errors is False


class TestStructuredLogger:
    def test_start_trace(self) -> None:
        log = StructuredLogger()
        trace = log.start_trace(session_id="s1", workflow_id="w1")
        assert trace.session_id == "s1"
        assert trace.workflow_id == "w1"
        assert trace.trace_id is not None
        assert trace.started_at != ""

    def test_start_span(self) -> None:
        log = StructuredLogger()
        trace = log.start_trace()
        span = log.start_span(trace, "llm_call", provider="anthropic", model="sonnet")
        assert span.name == "llm_call"
        assert span.provider == "anthropic"
        assert span.model == "sonnet"
        assert len(trace.spans) == 1

    def test_nested_spans(self) -> None:
        log = StructuredLogger()
        trace = log.start_trace()
        parent = log.start_span(trace, "workflow")
        child = log.start_span(trace, "node_exec", parent=parent)
        assert child.parent_span_id == parent.span_id
        assert len(trace.spans) == 2

    def test_end_span_sets_attrs(self) -> None:
        log = StructuredLogger()
        trace = log.start_trace()
        span = log.start_span(trace, "call")
        log.end_span(span, tokens_in=100, tokens_out=50, status="ok")
        assert span.tokens_in == 100
        assert span.tokens_out == 50
        assert span.status == "ok"
        assert span.ended_at is not None

    def test_end_span_extra_attrs(self) -> None:
        log = StructuredLogger()
        trace = log.start_trace()
        span = log.start_span(trace, "call")
        log.end_span(span, custom_field="hello")
        assert span.attributes["custom_field"] == "hello"

    def test_end_trace(self) -> None:
        log = StructuredLogger()
        trace = log.start_trace()
        log.end_trace(trace)
        assert trace.ended_at is not None


class TestTraceStorage:
    def test_append_and_query(self, tmp_path: Path) -> None:
        storage = TraceStorage(tmp_path / "traces")
        log = StructuredLogger()

        trace = log.start_trace(session_id="s1")
        span = log.start_span(trace, "test")
        log.end_span(span, tokens_in=10, tokens_out=5)
        log.end_trace(trace)

        storage.append(trace)

        loaded = storage.query("s1")
        assert len(loaded) == 1
        assert loaded[0].trace_id == trace.trace_id
        assert loaded[0].spans[0].tokens_in == 10

    def test_multiple_traces(self, tmp_path: Path) -> None:
        storage = TraceStorage(tmp_path / "traces")
        log = StructuredLogger()

        for i in range(3):
            trace = log.start_trace(session_id="s1")
            log.end_trace(trace)
            storage.append(trace)

        assert len(storage.query("s1")) == 3

    def test_list_sessions(self, tmp_path: Path) -> None:
        storage = TraceStorage(tmp_path / "traces")
        log = StructuredLogger()

        for sid in ["s1", "s2", "s3"]:
            trace = log.start_trace(session_id=sid)
            log.end_trace(trace)
            storage.append(trace)

        sessions = storage.list_sessions()
        assert set(sessions) == {"s1", "s2", "s3"}

    def test_get_latest(self, tmp_path: Path) -> None:
        storage = TraceStorage(tmp_path / "traces")
        log = StructuredLogger()

        for i in range(5):
            trace = log.start_trace(session_id="s1")
            log.end_trace(trace)
            storage.append(trace)

        latest = storage.get_latest("s1", limit=2)
        assert len(latest) == 2

    def test_query_empty_session(self, tmp_path: Path) -> None:
        storage = TraceStorage(tmp_path / "traces")
        assert storage.query("nonexistent") == []
