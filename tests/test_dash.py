"""/dash mission control: snapshot wiring, width-safe render, fallbacks, nav."""

from __future__ import annotations

import types

import pytest

from birkin import dash, ui


@pytest.fixture
def snap(monkeypatch):
    """A snapshot built from controllable backend stubs."""
    from birkin import approvals, budget, config, cron, store, transcripts

    monkeypatch.setattr(store, "read_status",
                        lambda: {"daemon": True,
                                 "heartbeat": "2099-01-01T00:00:00+00:00",
                                 "next_morpheus": "2026-07-25T04:00:00"})
    monkeypatch.setattr(store, "is_status_stale", lambda st: False)
    monkeypatch.setattr(budget, "status", lambda cfg: {
        "used_today": 82000, "used_month": 0, "daily_cap": 200000,
        "monthly_cap": 0, "over_daily": False, "over_monthly": False})
    monkeypatch.setattr(approvals, "reviewable_pending", lambda: [
        {"id": "a1", "category": "shell", "title": "rm -rf 빌드 디렉터리 정리",
         "status": "pending"},
        {"id": "a2", "category": "cron", "title": "아침 브리핑", "status": "pending"}])
    monkeypatch.setattr(cron, "load_jobs", lambda: [
        {"name": "morning-briefing", "next_run": "2026-07-25T09:00:00",
         "enabled": True, "id": "c1"}])
    monkeypatch.setattr(cron, "schedule_display", lambda j: "09:00")

    class _Dex:
        def entries(self):
            return {}

    class _Mem:
        def __init__(self, cfg):
            pass

        def list_notes(self):
            return [{"zone": "kubernetes"}, {"zone": "kubernetes"},
                    {"zone": "inbox"}]
    monkeypatch.setattr("birkin.memory.Memory", _Mem)

    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    (d / "20260528-대화.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(config, "sessions_dir", lambda: d)
    monkeypatch.setattr(transcripts, "is_auto", lambda stem: False)

    sess = types.SimpleNamespace(cfg={"model": "gpt-5.6-sol",
                                      "provider": "codex-cli"})
    return dash.snapshot(sess)


# -- snapshot wiring -------------------------------------------------------

def test_snapshot_gathers_every_pane(snap):
    assert snap["header"]["model"] == "gpt-5.6-sol"
    assert snap["header"]["daemon_up"] is True
    assert len(snap["sessions"]) == 1
    assert len(snap["cron"]) == 1 and snap["cron"][0]["schedule"] == "09:00"
    assert len(snap["approvals"]) == 2
    zones = {z["zone"]: z["count"] for z in snap["zones"]}
    assert zones == {"kubernetes": 2, "inbox": 1}


def test_zones_sorted_by_count_desc(snap):
    assert snap["zones"][0]["zone"] == "kubernetes"


# -- render is width-safe for CJK -----------------------------------------

@pytest.mark.parametrize("section", ["세션", "크론", "승인", "기억"])
@pytest.mark.parametrize("cols", [70, 92, 120])
def test_render_never_overflows_terminal_width(snap, section, cols):
    state = {"section": section, "cursor": 0, "top": 0}
    frame = dash.render(snap, state, (cols, 24))
    over = [ln for ln in frame if ui.cell_width(ln) > cols]
    assert not over, f"{len(over)} line(s) overflow {cols} cols in {section}"


def test_render_fits_within_row_height(snap):
    frame = dash.render(snap, {"section": "세션", "cursor": 0, "top": 0}, (92, 20))
    assert len(frame) <= 20


def test_active_section_marked_and_cursor_highlighted(snap):
    frame = dash.render(snap, {"section": "승인", "cursor": 0, "top": 0}, (92, 24))
    plain = ui._ANSI_RE.sub("", "\n".join(frame))
    assert "▸3 승인" in plain                       # active rail marker
    # The cursor row carries an ASCII "> " marker (after the rail divider) so it
    # reads even with color off (pytest is non-tty); inverse layers on when on.
    assert "│ > " in plain, "cursor row has no color-independent marker"


def test_empty_section_shows_placeholder(monkeypatch, snap):
    snap["sessions"] = []
    frame = dash.render(snap, {"section": "세션", "cursor": 0, "top": 0}, (80, 24))
    assert any("(없음)" in ui._ANSI_RE.sub("", ln) for ln in frame)


# -- plain / json fallback -------------------------------------------------

def test_dump_plain_labels_every_section(snap):
    out = dash.dump_plain(snap)
    for s in ("세션", "크론", "승인", "기억"):
        assert f"[{s}]" in out
    assert "morning-briefing" in out


def test_dump_json_is_valid_and_excludes_cfg(snap):
    import json
    out = dash.dump_json = dash.dump_plain(snap, as_json=True)
    data = json.loads(out)
    assert "cfg" not in data
    assert data["header"]["model"] == "gpt-5.6-sol"
    assert len(data["approvals"]) == 2


def test_run_falls_back_to_plain_when_not_tty(snap, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdout.isatty", lambda: False, raising=False)
    sess = types.SimpleNamespace(cfg={"model": "m", "provider": "p"})
    dash.run(sess)     # must not touch escapes / keyboard
    out = capsys.readouterr().out
    assert "mission control" in out


# -- cursor navigation math ------------------------------------------------

def test_clamp_keeps_cursor_in_range(snap):
    state = {"section": "승인", "cursor": 99, "top": 0}
    dash._clamp_cursor(snap, state, body_h=10)
    assert state["cursor"] == len(snap["approvals"]) - 1


def test_clamp_scrolls_the_window(snap):
    snap["approvals"] = [{"id": str(i), "category": "x", "title": f"t{i}",
                          "status": "p"} for i in range(50)]
    state = {"section": "승인", "cursor": 30, "top": 0}
    dash._clamp_cursor(snap, state, body_h=10)
    assert state["top"] <= 30 < state["top"] + 10


def test_dash_command_registered():
    import birkin.repl  # noqa: F401
    from birkin import slashcommands
    assert "dash" in slashcommands._REGISTRY
