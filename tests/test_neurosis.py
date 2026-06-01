"""Tests for the neurosis deep-interview runtime + surface wiring."""

from __future__ import annotations

import json
import types

import pytest

from birkin import neurosis


def test_resolve_threshold_precedence():
    # explicit override wins
    assert neurosis.resolve_threshold({}, override=0.2) == (0.2, "flag:--threshold")
    # config next
    assert neurosis.resolve_threshold({"neurosis_threshold": 0.1}) == (0.1, "config")
    # resolution preset next
    assert neurosis.resolve_threshold({}, resolution="deep") == (0.35, "flag:--deep")
    # default last
    assert neurosis.resolve_threshold({}) == (0.05, "default")
    # invalid override/config ignored -> falls through
    assert neurosis.resolve_threshold({"neurosis_threshold": 9}) == (0.05, "default")


def test_slug():
    assert neurosis._slug("Build a CRM!! for sales") == "build-a-crm-for-sales"
    assert neurosis._slug("   ").startswith("idea-")  # fallback when empty


def test_seed_state_writes_resumable_file(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    seed = neurosis.seed_state("a tool that schedules posts", cfg={}, resolution="standard")
    assert seed["resume"] is False
    assert seed["threshold"] == 0.5 and seed["threshold_source"] == "flag:--standard"
    assert seed["threshold_percent"] == "50%"
    sp = tmp_path / "neurosis" / f"{seed['slug']}.json"
    assert sp.exists()
    rec = json.loads(sp.read_text(encoding="utf-8"))
    assert rec["active"] is True and rec["skill"] == "neurosis"
    assert rec["state"]["initial_idea"] == "a tool that schedules posts"
    assert rec["state"]["rounds"] == [] and rec["state"]["current_ambiguity"] == 1.0
    assert seed["spec_path"].endswith(f"neurosis-{seed['slug']}.md")


def test_seed_or_resume_new_vs_resume_vs_none(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    # no idea, nothing active -> None
    assert neurosis.seed_or_resume("", cfg={}) is None
    # idea -> new
    s1 = neurosis.seed_or_resume("first idea", cfg={})
    assert s1 and s1["resume"] is False
    # no idea now resumes the most recent active
    r = neurosis.seed_or_resume("", cfg={})
    assert r and r["resume"] is True and r["slug"] == s1["slug"]


def test_reseed_same_idea_resumes_not_clobbers(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import store
    s1 = neurosis.seed_state("build a CRM", cfg={})
    sp = tmp_path / "neurosis" / f"{s1['slug']}.json"
    rec = json.loads(sp.read_text(encoding="utf-8"))
    rec["state"]["rounds"].append({"q": "first question", "a": "answer"})
    store._write_json(sp, rec)
    # re-seeding the SAME idea must resume, not wipe the in-progress rounds
    s2 = neurosis.seed_state("build a CRM", cfg={})
    assert s2["resume"] is True and s2["slug"] == s1["slug"]
    assert len(json.loads(sp.read_text(encoding="utf-8"))["state"]["rounds"]) == 1


def test_gateway_neurosis_parses_resolution_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    config.save_config({**config.DEFAULT_CONFIG, "provider": "claude-cli",
                        "gateway_persistent": False})
    from birkin.gateway.core import Gateway
    gw = Gateway(config.load_config())
    monkeypatch.setattr(gw.session, "ask", lambda text, **k: "Q?")
    gw.handle("http", "c1", "/neurosis --deep build a CRM")
    files = list((tmp_path / "neurosis").glob("*.json"))
    assert len(files) == 1 and files[0].stem == "build-a-crm"   # flag not in slug
    rec = json.loads(files[0].read_text(encoding="utf-8"))
    assert rec["state"]["initial_idea"] == "build a CRM"        # flag not in idea
    assert rec["threshold"] == 0.35                             # --deep applied


def test_skill_path_found():
    sk = neurosis.skill_path()
    assert sk is not None and sk.name == "SKILL.md" and sk.parent.name == "neurosis"


def test_start_prompt_contains_run_params(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    seed = neurosis.seed_state("vague idea", cfg={}, resolution="deep")
    p = neurosis.start_prompt(seed)
    assert "neurosis" in p and "vague idea" in p
    assert seed["state_path"] in p and seed["spec_path"] in p
    assert "35%" in p
    # resume variant
    rp = neurosis.start_prompt({**seed, "resume": True})
    assert "Resume" in rp and seed["state_path"] in rp


def test_cli_neurosis_seeds(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import cli
    rc = cli._cmd_neurosis(types.SimpleNamespace(idea=["build", "a", "thing", "--quick"]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "neurosis" in out and "60%" in out  # quick preset
    assert list((tmp_path / "neurosis").glob("*.json"))


def test_cli_neurosis_requires_idea(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import cli
    assert cli._cmd_neurosis(types.SimpleNamespace(idea=[])) == 1


def test_gateway_neurosis_starts_interview(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    config.save_config({**config.DEFAULT_CONFIG, "provider": "claude-cli",
                        "gateway_persistent": False})
    from birkin.gateway.core import Gateway
    captured = {}

    gw = Gateway(config.load_config())

    def fake_ask(text, **k):
        captured["prompt"] = text
        return "딥 인터뷰 임계값: 5% ...\nRound 0 질문?"
    monkeypatch.setattr(gw.session, "ask", fake_ask)

    reply = gw.handle("http", "c1", "/neurosis build a CRM")
    assert "Round 0" in reply
    # the agent received the kickoff prompt, not the raw slash command
    assert "neurosis" in captured["prompt"] and "build a CRM" in captured["prompt"]
    # a resumable interview state was seeded
    assert list((tmp_path / "neurosis").glob("*.json"))


def test_gateway_neurosis_no_idea_no_active(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    config.save_config({**config.DEFAULT_CONFIG, "provider": "claude-cli",
                        "gateway_persistent": False})
    from birkin.gateway.core import Gateway
    gw = Gateway(config.load_config())
    reply = gw.handle("http", "c1", "/neurosis")
    assert "아이디어" in reply  # asks for an idea (Korean), no LLM turn


def test_slash_neurosis_kicks_off(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import slashcommands
    captured = {}
    sess = types.SimpleNamespace(
        cfg={}, ask=lambda text, **k: captured.setdefault("prompt", text) or "")
    # sys_write calls session.ask + store.append_activity; both are safe here
    slashcommands._neurosis(sess, "build a thing --standard")
    assert "neurosis" in captured["prompt"] and "build a thing" in captured["prompt"]
    assert list((tmp_path / "neurosis").glob("*.json"))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
