"""Odyssey (v2) — goal-cycle seed + kickoff prompt."""

from __future__ import annotations

import json
from pathlib import Path

from birkin import boulder, odyssey
from tests.test_native_private_storage import assert_owner_only


def test_seed_derives_slug_and_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    s = odyssey.seed("Build a CRM for sales", cfg={})
    assert s["slug"] == "build-a-crm-for-sales"
    assert s["boulder_path"].endswith(f"{s['slug']}.json")
    assert s["resume"] is False


def test_seed_persists_inactive_boulder_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))

    seeded = odyssey.seed(
        "C001 approved Odyssey sentinel",
        cfg={"boulder_max_iters": 17, "critique_agents": 5},
    )

    path = Path(seeded["boulder_path"])
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record == {
        "goal": "C001 approved Odyssey sentinel",
        "slug": seeded["slug"],
        "created_at": record["created_at"],
        "max_iters": 17,
        "critics": 5,
        "seeded": True,
        "active": False,
        "steps": [],
    }
    assert record["created_at"]
    assert boulder.active() == []

    assert_owner_only(path.parent, posix_mode=0o700)
    assert_owner_only(path, posix_mode=0o600)


def test_seed_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    first = odyssey.seed("C001 stable seed", cfg={"boulder_max_iters": 17})
    path = Path(first["boulder_path"])
    original = path.read_bytes()

    second = odyssey.seed("C001 stable seed", cfg={"boulder_max_iters": 99})

    assert path.read_bytes() == original
    assert second["max_iters"] == 17


def test_seed_resumes_active_plan_without_overwriting_it(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    boulder.create("Build a CRM for sales", ["step one"])
    path = tmp_path / "boulder" / "build-a-crm-for-sales.json"
    original = path.read_bytes()

    s = odyssey.seed("Build a CRM for sales", cfg={})

    assert s["resume"] is True
    assert path.read_bytes() == original


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
