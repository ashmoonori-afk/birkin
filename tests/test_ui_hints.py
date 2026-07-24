"""Discoverability: hint(), the checkpoint/steer nudges, and event wiring."""

from __future__ import annotations

import contextlib
import io

from birkin import ui


def _emit_capture(event, payload):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ui.make_event_printer()(event, payload)
    return buf.getvalue()


def test_hint_prints_joined_parts():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ui.hint("[y] 승인", "[n] 거부", "esc 취소")
    out = buf.getvalue()
    assert "[y] 승인" in out and "[n] 거부" in out and "esc 취소" in out
    assert out.endswith("\n")


def test_hint_with_no_parts_is_silent():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ui.hint()
    assert buf.getvalue() == ""


def test_checkpoint_event_teaches_undo():
    out = _emit_capture("checkpoint", {"before": "write_file"})
    assert "checkpoint" in out and "/undo" in out


def test_steer_event_shows_reflected_text():
    out = _emit_capture("steer", {"text": "also check the logs"})
    assert "steer" in out and "also check the logs" in out


def test_unknown_event_is_ignored():
    assert _emit_capture("nonsense", {}) == ""


def test_checkpoint_preflight_emits_when_a_snapshot_is_taken(monkeypatch):
    """The event must fire from real checkpoint plumbing, not be a dead branch."""
    from birkin import checkpoints
    events = []

    class Mgr:
        enabled = True

        def ensure_checkpoint(self, workdir, reason=""):
            return "deadbeef"          # a real snapshot happened

    class Ctx:
        checkpoints = Mgr()
        cwd = "."
        emit = staticmethod(lambda e, p: events.append((e, p)))

    monkeypatch.setattr(checkpoints, "project_root_for", lambda p: ".")
    checkpoints.preflight(Ctx(), "write_file", {"path": "x.py"})
    assert ("checkpoint", {"before": "write_file"}) in events


def test_checkpoint_preflight_silent_when_no_snapshot(monkeypatch):
    from birkin import checkpoints
    events = []

    class Mgr:
        enabled = True

        def ensure_checkpoint(self, workdir, reason=""):
            return None                # no change -> no snapshot -> no event

    class Ctx:
        checkpoints = Mgr()
        cwd = "."
        emit = staticmethod(lambda e, p: events.append((e, p)))

    monkeypatch.setattr(checkpoints, "project_root_for", lambda p: ".")
    checkpoints.preflight(Ctx(), "write_file", {"path": "x.py"})
    assert events == []


def test_question_mark_routes_to_help(monkeypatch):
    # The repl maps a bare "?" to /help; verify the command exists to receive it.
    from birkin import slashcommands
    assert "help" in slashcommands._REGISTRY
