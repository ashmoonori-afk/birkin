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


def test_odyssey_entry_points_exist(tmp_path, monkeypatch):
    """The bundled skill advertises /odyssey and `birkin odyssey` — both must
    actually exist. They did not: the launcher was written but never wired."""
    from birkin import slashcommands
    assert "odyssey" in slashcommands._REGISTRY
    assert slashcommands._ALIASES.get("ulw") == "odyssey"

    from birkin.cli import build_parser
    args = build_parser().parse_args(["odyssey", "ship the thing"])
    assert args.func.__name__ == "_cmd_odyssey"


def test_odyssey_cli_seeds_a_plan_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin.cli import _cmd_odyssey
    import argparse
    rc = _cmd_odyssey(argparse.Namespace(goal=["배포", "자동화"]))
    out = capsys.readouterr().out
    assert rc == 0 and "배포-자동화" in out


def test_odyssey_cli_rejects_an_empty_goal(capsys):
    from birkin.cli import _cmd_odyssey
    import argparse
    assert _cmd_odyssey(argparse.Namespace(goal=[])) == 1
