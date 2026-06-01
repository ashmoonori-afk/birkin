"""Odyssey (v2) — goal-cycle seed + kickoff prompt."""

from __future__ import annotations

from birkin import boulder, odyssey


def test_seed_derives_slug_and_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    s = odyssey.seed("Build a CRM for sales", cfg={})
    assert s["slug"] == "build-a-crm-for-sales"
    assert s["boulder_path"].endswith(f"{s['slug']}.json")
    assert s["resume"] is False


def test_seed_resumes_active_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    boulder.create("Build a CRM for sales", ["step one"])     # active plan exists
    s = odyssey.seed("Build a CRM for sales", cfg={})
    assert s["resume"] is True


def test_start_prompt_drives_the_cycle(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    s = odyssey.seed("ship the export feature", cfg={"critique_agents": 4})
    p = odyssey.start_prompt(s)
    assert "[Odyssey]" in p and "ship the export feature" in p
    assert "[Osiris]" in p and s["boulder_path"] in p
    assert "load_skill('odyssey')" in p and "4 adversarial critics" in p
