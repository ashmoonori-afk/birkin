"""/dash and the web dashboard must not report false calm.

Three separate places said "everything is fine" when it was not:

1. ``snapshot()`` wrapped every backend in a bare ``except Exception: pass``,
   so a broken approval store rendered as an empty 승인 pane — identical to
   having nothing pending. The pane that exists to say "these actions need
   you" was the one that could silently say "nothing does".
2. ``_resolve_approval`` swallowed its result, so approving a queued shell
   command from /dash showed nothing at all — success, non-zero exit and a
   raised exception were indistinguishable.
3. The web dashboard labelled every run a green "Complete", because run
   records carry no ``status`` field for it to read.
"""

from __future__ import annotations

import types

import pytest

from birkin import dash


def _session():
    return types.SimpleNamespace(cfg={"model": "m", "provider": "p"})


def _snap_with_error(section: str = "승인", message: str = "디스크 터짐"):
    snap = {"header": {"model": "m", "provider": "p"},
            "sessions": [], "agents": [], "cron": [], "approvals": [],
            "zones": [], "errors": {section: message}}
    return snap


# -- 1. a broken backend is not an empty one -------------------------------

def test_snapshot_records_a_failing_source(monkeypatch):
    from birkin import approvals
    monkeypatch.setattr(approvals, "reviewable_pending",
                        lambda: (_ for _ in ()).throw(OSError("승인함 못 읽음")))
    snap = dash.snapshot(_session())
    assert snap["approvals"] == []
    assert "승인" in snap.get("errors", {}), (
        "the approval store blew up and the snapshot said nothing")
    assert "승인함 못 읽음" in snap["errors"]["승인"]


def test_snapshot_healthy_source_records_no_error(monkeypatch):
    from birkin import approvals
    monkeypatch.setattr(approvals, "reviewable_pending", lambda: [])
    snap = dash.snapshot(_session())
    assert "승인" not in snap.get("errors", {})


def test_failed_pane_says_failed_not_empty():
    lines = dash._table_lines(_snap_with_error(), "승인", 0, 0, 20, 60)
    body = "\n".join(lines)
    assert "실패" in body, "an errored pane still renders as merely empty"
    assert "디스크 터짐" in body, "the reason is dropped"
    assert "(없음)" not in body, "'nothing pending' is a lie here"


def test_healthy_empty_pane_still_says_empty():
    snap = _snap_with_error(section="크론")
    lines = dash._table_lines(snap, "승인", 0, 0, 20, 60)
    body = "\n".join(lines)
    assert "(없음)" in body
    assert "실패" not in body


def test_rail_count_stops_claiming_zero_when_broken():
    rail = "\n".join(dash._rail_lines(_snap_with_error(), "세션", 8))
    assert "승인 0" not in rail, "the glance count still reports a confident 0"
    assert "!" in rail


def test_error_line_does_not_silently_eat_a_row():
    """The error line is chrome too — capacity has to account for it."""
    snap = {"header": {"model": "m", "provider": "p"},
            "sessions": [{"title": f"SESSION-{i:04d}", "age": "1h"}
                         for i in range(40)],
            "agents": [], "cron": [], "approvals": [], "zones": [],
            "errors": {"세션": "일부만 읽음"}}
    height = dash._body_h(24)
    lines = dash._table_lines(snap, "세션", 0, 0, height, 60)
    assert len(lines) <= height, (
        f"table built {len(lines)} lines for a {height}-line slot")
    assert any("더 있음" in l for l in lines), "overflow indicator lost again"


def test_dump_plain_reports_the_failure():
    out = dash.dump_plain(_snap_with_error())
    assert "실패" in out and "디스크 터짐" in out


def test_dump_json_carries_the_errors():
    import json
    out = json.loads(dash.dump_plain(_snap_with_error(), as_json=True))
    assert out["errors"]["승인"] == "디스크 터짐"


# -- 2. approving something must tell you what happened --------------------

def test_resolve_approval_returns_the_outcome(monkeypatch):
    from birkin import approvals
    monkeypatch.setattr(approvals, "approve",
                        lambda aid: {"ok": True, "result": "실행됨: exit 0"})
    out = dash._resolve_approval({"id": "abc"}, approve=True)
    assert out["ok"] is True
    assert "exit 0" in str(out.get("result"))


def test_resolve_approval_surfaces_a_failure(monkeypatch):
    from birkin import approvals
    monkeypatch.setattr(approvals, "approve",
                        lambda aid: {"ok": False, "error": "action failed: 권한 없음"})
    out = dash._resolve_approval({"id": "abc"}, approve=True)
    assert out["ok"] is False
    assert "권한 없음" in out["error"]


def test_resolve_approval_survives_an_exception(monkeypatch):
    from birkin import approvals

    def boom(aid):
        raise RuntimeError("승인함 잠김")
    monkeypatch.setattr(approvals, "approve", boom)
    out = dash._resolve_approval({"id": "abc"}, approve=True)
    assert out["ok"] is False
    assert "승인함 잠김" in out["error"], "the exception vanished"


def test_hint_line_shows_the_outcome_note():
    plain = dash._hint_line("승인", 200)
    noted = dash._hint_line("승인", 200, note="⚠ action failed: 권한 없음")
    assert "권한 없음" in noted
    assert "권한 없음" not in plain


def test_render_paints_the_note():
    snap = {"header": {"model": "m", "provider": "p"}, "sessions": [],
            "agents": [], "cron": [], "approvals": [], "zones": [],
            "errors": {}}
    state = {"section": "승인", "cursor": 0, "top": 0,
             "note": "⚠ action failed: 권한 없음"}
    frame = dash.render(snap, state, (100, 24))
    assert any("권한 없음" in line for line in frame)


# -- 3. the web dashboard must not call a failed run "Complete" ------------

def _index_html() -> str:
    from pathlib import Path
    import birkin
    return (Path(birkin.__file__).parent / "web" / "static"
            / "index.html").read_text(encoding="utf-8")


def test_run_badge_does_not_default_to_green_complete():
    """save_run() writes no `status` and no top-level `error` (store.py), so
    `item.status||(item.error?...:"Complete")` resolved to a green Complete for
    every run ever recorded — including ones that crashed."""
    html = _index_html()
    assert '"Complete"' not in html, (
        "runs still default to a green Complete badge")


def test_run_badge_reads_the_error_that_is_actually_written():
    """moirai records failures under details.error (engine.py); nothing writes
    a top-level `error`, which is why the old check never fired."""
    html = _index_html()
    assert "details||{}).error" in html or "details || {}).error" in html, (
        "the badge still ignores details.error, the one signal that exists")


def test_run_tone_is_not_unconditionally_good():
    html = _index_html()
    assert '?"danger":"good"' not in html, (
        "a run with no status still paints a green dot")
