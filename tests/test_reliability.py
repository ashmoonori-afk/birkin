"""Tests for the reliability control plane (P3):
stale heartbeat, budget governor, trace command."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone


from birkin import budget, cli as cli_mod, config, runtime, store


# ---------------- stale heartbeat ----------------

def test_status_not_stale_when_fresh():
    store.write_status({"daemon": True, "next_nightly": ""})
    st = store.read_status()
    assert store.is_status_stale(st) is False


def test_status_stale_when_heartbeat_old():
    store.write_status({"daemon": True})
    st = store.read_status()
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    st["heartbeat"] = old
    assert store.is_status_stale(st) is True


def test_status_no_heartbeat_returns_false():
    assert store.is_status_stale({"daemon": False}) is False


def test_status_garbage_heartbeat_is_stale():
    assert store.is_status_stale({"daemon": True, "heartbeat": "nonsense"}) is True


# ---------------- budget governor ----------------

def test_budget_status_under_cap():
    store.save_run("chat", "a", usage=store.estimate_usage("x" * 40))
    st = budget.status({"budget_tokens_daily": 1000, "budget_tokens_monthly": 0})
    assert st["used_today"] > 0
    assert st["over_daily"] is False


def test_budget_status_over_cap_when_breached():
    store.save_run("chat", "a", usage={"chars": 0, "words": 0, "estTokens": 50})
    st = budget.status({"budget_tokens_daily": 10, "budget_tokens_monthly": 0})
    assert st["over_daily"] is True
    over, msg = budget.is_over({"budget_tokens_daily": 10})
    assert over is True
    assert "budget" in msg.lower() and "reached" in msg.lower()


def test_budget_zero_is_unlimited():
    store.save_run("chat", "a", usage={"chars": 0, "words": 0, "estTokens": 1_000_000})
    assert budget.is_over({})[0] is False
    assert budget.status({})["over_daily"] is False


def test_runtime_ask_blocks_when_over_budget(monkeypatch):
    """Over-budget ask() must NOT call the client (no LLM spend) and must
    write a 'skipped: over-budget' run record."""
    cfg = {"provider": "codex-cli", "model": "",
           "budget_tokens_daily": 1, "budget_tokens_monthly": 0}
    # seed a run that breaches the cap
    store.save_run("chat", "prior", usage={"chars": 0, "words": 0, "estTokens": 9999})
    s = runtime.build_session(cfg)

    # If ask DID call the client, this would raise — proving the gate works.
    def boom(*a, **kw):
        raise AssertionError("client.complete must not be called over budget")
    monkeypatch.setattr(s.client, "complete", boom)

    reply = s.ask("anything")
    assert "budget" in reply.lower() and "reached" in reply.lower()
    # a refusal run record exists
    assert any("over-budget" in r["summary"]
               for r in store.list_runs() if r["kind"] == "chat")


# ---------------- birkin trace ----------------

def test_cmd_trace_prints_record(capsys):
    path = store.save_run("chat", "hello world",
                          details={"tools": ["read_file"], "provider": "anthropic"},
                          usage=store.estimate_usage("a" * 40))
    rid = path.stem.split("-chat")[0]   # e.g. "20260528-1234-abcd-chat" -> "20260528-1234-abcd"
    ns = argparse.Namespace(run_id=rid)
    rc = cli_mod._cmd_trace(ns)
    out = capsys.readouterr().out
    assert rc == 0
    assert rid in out
    assert "hello world" in out
    assert "read_file" in out


def test_cmd_trace_missing(capsys):
    rc = cli_mod._cmd_trace(argparse.Namespace(run_id="no-such-id"))
    assert rc == 1
    assert "No run" in capsys.readouterr().out


def test_cmd_trace_no_id(capsys):
    rc = cli_mod._cmd_trace(argparse.Namespace(run_id=""))
    assert rc == 1


# ---------------- birkin budget command ----------------

def test_cmd_budget_prints_status(capsys, monkeypatch):
    store.save_run("chat", "a", usage={"chars": 0, "words": 0, "estTokens": 25})
    cfg = config.load_config()
    cfg["budget_tokens_daily"] = 10
    config.save_config(cfg)
    rc = cli_mod._cmd_budget(argparse.Namespace())
    out = capsys.readouterr().out
    assert rc == 0
    assert "Token budget" in out and "OVER" in out
