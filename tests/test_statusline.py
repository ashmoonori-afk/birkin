"""The reprinted status line, wired to real backend shapes."""

from __future__ import annotations

import pytest

from birkin import statusline, ui


@pytest.fixture
def wired(monkeypatch):
    """Point the status line at controllable backend stubs."""
    from birkin import approvals, budget, store
    state = {
        "status": {"daemon": True,
                   "heartbeat": "2099-01-01T00:00:00+00:00",
                   "next_morpheus": "2026-07-25T04:00:00"},
        "stale": False,
        "budget": {"used_today": 0, "used_month": 0, "daily_cap": 0,
                   "monthly_cap": 0, "over_daily": False, "over_monthly": False},
        "pending": [],
    }
    monkeypatch.setattr(store, "read_status", lambda: state["status"])
    monkeypatch.setattr(store, "is_status_stale", lambda st: state["stale"])
    monkeypatch.setattr(budget, "status", lambda cfg: state["budget"])
    monkeypatch.setattr(approvals, "reviewable_pending", lambda: state["pending"])
    return state


def _cfg(**kw):
    base = {"model": "gpt-5.6-sol", "provider": "codex-cli"}
    base.update(kw)
    return base


def test_identity_is_always_present(wired):
    line = statusline.build(_cfg())
    assert "gpt-5.6-sol" in line and "codex-cli" in line


def test_long_model_id_is_truncated_color_safe(wired):
    line = statusline.build(_cfg(model="claude-haiku-4-5-20251001-preview-xl"))
    assert "…" in line
    # The colored line's display width ignores escapes and stays bounded.
    assert ui.cell_width(line) < 80


def test_daemon_up_shown_when_alive(wired):
    assert "●up" in statusline.build(_cfg())


def test_daemon_stale_shown_when_heartbeat_old(wired):
    wired["stale"] = True
    assert "◐stale" in statusline.build(_cfg())


def test_daemon_hidden_when_never_ran(wired):
    wired["status"] = {"daemon": False}      # no heartbeat, never started
    line = statusline.build(_cfg())
    assert "up" not in line and "stale" not in line


def test_morpheus_time_shown_as_hhmm(wired):
    assert "morpheus 04:00" in statusline.build(_cfg())


def test_budget_hidden_without_a_cap(wired):
    # This machine's default: no cap, no usage -> segment omitted entirely.
    assert "tok" not in statusline.build(_cfg())


def test_budget_shows_bare_tokens_when_used_but_uncapped(wired):
    wired["budget"]["used_today"] = 42000
    line = statusline.build(_cfg())
    assert "tok 42k" in line
    assert "/" not in line.split("tok 42k")[1][:4]   # no cap gauge


def test_budget_gauge_and_severity_when_capped(wired):
    wired["budget"].update(used_today=164000, daily_cap=200000)
    line = statusline.build(_cfg())
    assert "tok 164k/200k" in line
    assert ui.bar(164000 / 200000, 6) in line


def test_over_budget_is_flagged(wired):
    wired["budget"].update(used_today=210000, daily_cap=200000, over_daily=True)
    assert "tok 210k/200k" in statusline.build(_cfg())


def test_pending_shown_only_when_nonzero(wired):
    assert "⚑" not in statusline.build(_cfg())
    wired["pending"] = [{"id": "a"}, {"id": "b"}]
    assert "⚑2" in statusline.build(_cfg())


def test_render_adds_a_gutter(wired):
    assert statusline.render(_cfg()).startswith("  ")


def test_survives_backend_errors(wired, monkeypatch):
    from birkin import store
    monkeypatch.setattr(store, "read_status",
                        lambda: (_ for _ in ()).throw(OSError("no disk")))
    # Identity must still render even if a backend blows up.
    line = statusline.build(_cfg())
    assert "gpt-5.6-sol" in line


def test_k_humanizer():
    assert statusline._k(0) == "0"
    assert statusline._k(999) == "999"
    assert statusline._k(82000) == "82k"
    assert statusline._k(1_400_000) == "1.4M"
