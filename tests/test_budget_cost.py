"""Cost in dollars, so the pitch never has to rest on who gets billed.

The 'free on a subscription' framing is retired (ADR-050); what replaces it
is being able to say what a day of birkin actually costs at list rates, and
whether that fits the credit envelope Anthropic announced.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from birkin import budget, config, store


def test_cost_scales_with_tokens_and_model_tier():
    cheap = budget.estimate_cost_usd(1_000_000, "haiku")
    mid = budget.estimate_cost_usd(1_000_000, "sonnet")
    dear = budget.estimate_cost_usd(1_000_000, "opus")
    assert 0 < cheap < mid < dear
    assert budget.estimate_cost_usd(2_000_000, "sonnet") == pytest.approx(
        2 * mid)


def test_zero_and_negative_tokens_cost_nothing():
    assert budget.estimate_cost_usd(0, "opus") == 0
    assert budget.estimate_cost_usd(-5, "opus") == 0


def test_unknown_model_falls_back_rather_than_raising():
    assert budget.estimate_cost_usd(1_000_000, "some-new-model") > 0
    assert budget.estimate_cost_usd(1_000_000, "") > 0


def test_output_fraction_moves_the_estimate_between_the_two_rates():
    inp_only = budget.estimate_cost_usd(1_000_000, "sonnet",
                                        output_fraction=0.0)
    out_only = budget.estimate_cost_usd(1_000_000, "sonnet",
                                        output_fraction=1.0)
    assert inp_only == pytest.approx(3.0)
    assert out_only == pytest.approx(15.0)
    # clamped, not exploding, on a nonsense fraction
    assert budget.estimate_cost_usd(1_000_000, "sonnet",
                                    output_fraction=9.0) == out_only


def test_announced_credit_tiers_are_the_published_ones():
    assert budget.ANNOUNCED_CREDIT_TIERS_USD == {
        "pro": 20, "max5x": 100, "max20x": 200}


def test_budget_command_reports_dollars_and_a_tier_verdict(tmp_path,
                                                           monkeypatch,
                                                           capsys):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import ledger
    from birkin.cli import _cmd_budget
    ledger.event("turn", "a turn", tokens=500_000)
    import argparse
    assert _cmd_budget(argparse.Namespace()) == 0
    out = capsys.readouterr().out
    assert "At API list rates" in out and "$" in out
    assert "credit tier" in out


def test_monthly_budget_reads_all_in_window_runs_when_ledger_exceeds_limit(
    tmp_path, monkeypatch,
):
    # Given: 1,200 current runs and 300 stale runs in a 1,500-record ledger.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    recent_at = datetime.now(timezone.utc) - timedelta(days=1)
    stale_at = datetime.now(timezone.utc) - timedelta(days=31)
    runs_dir = config.runs_dir()
    for index in range(1_200):
        record = {
            "id": f"recent-{index}",
            "kind": "chat",
            "at": recent_at.isoformat(),
            "summary": "recent",
            "usage": {"estTokens": 100},
        }
        name = f"{recent_at.strftime('%Y%m%d-%H%M%S')}-{index:04d}-chat.json"
        (runs_dir / name).write_text(json.dumps(record), encoding="utf-8")
    for index in range(300):
        record = {
            "id": f"stale-{index}",
            "kind": "chat",
            "at": stale_at.isoformat(),
            "summary": "stale",
            "usage": {"estTokens": 100},
        }
        name = f"{stale_at.strftime('%Y%m%d-%H%M%S')}-{index:04d}-chat.json"
        (runs_dir / name).write_text(json.dumps(record), encoding="utf-8")

    reads = 0
    read_json = store._read_json

    def count_reads(*args, **kwargs):
        nonlocal reads
        reads += 1
        return read_json(*args, **kwargs)

    monkeypatch.setattr(store, "_read_json", count_reads)

    # When: the monthly budget window is calculated.
    used = budget.usage_window(24 * 30)

    # Then: every current run counts, while stale JSON stays unopened.
    assert used == 120_000
    assert reads == 1_200
    over, _ = budget.is_over({"budget_tokens_monthly": 120_000})
    assert over is True
