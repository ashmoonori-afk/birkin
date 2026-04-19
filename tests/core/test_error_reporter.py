"""Tests for ErrorReporter."""

from __future__ import annotations

from birkin.core.error_reporter import ErrorReporter, ErrorSeverity


class TestErrorReporter:
    def test_add_and_drain(self):
        r = ErrorReporter()
        r.add(ErrorSeverity.WARNING, "memory", "Save failed")
        errors = r.drain()
        assert len(errors) == 1
        assert errors[0].component == "memory"
        assert errors[0].severity == ErrorSeverity.WARNING

    def test_drain_clears(self):
        r = ErrorReporter()
        r.add(ErrorSeverity.ERROR, "workflow", "Node failed")
        r.drain()
        assert r.drain() == []

    def test_has_errors(self):
        r = ErrorReporter()
        assert not r.has_errors()
        r.add(ErrorSeverity.INFO, "recommender", "No suggestions")
        assert r.has_errors()

    def test_to_chat_metadata(self):
        r = ErrorReporter()
        r.add(ErrorSeverity.WARNING, "memory", "Fail")
        meta = r.to_chat_metadata()
        assert len(meta) == 1
        assert meta[0]["severity"] == "warning"
        assert meta[0]["component"] == "memory"
        assert meta[0]["message"] == "Fail"
