from __future__ import annotations

import json
import types

import pytest

from birkin import config, slashcommands as sc
from birkin.memory import VaultMemory
from birkin.rolefiles import ProfileEdit, ProfileStore


def _session(write_approval=True):
    cfg = config.load_config()
    cfg["profile"] = {**cfg["profile"], "enabled": True, "write_approval": write_approval}
    return types.SimpleNamespace(cfg=cfg, memory=VaultMemory(cfg))


def test_pending_approve_reject_round_trip_survives_restart(capsys):
    session = _session(True)
    actions = session.memory.profile_actions()
    first = actions.submit(ProfileEdit("preferences", "add", content="tone: concise"), trusted=True, source="test")
    second = actions.submit(ProfileEdit("preferences", "add", content="lang: Korean"), trusted=True, source="test")

    restarted = _session(True)
    sc.dispatch(restarted, "/profile pending")
    out = capsys.readouterr().out
    assert first.id in out and second.id in out

    sc.dispatch(restarted, f"/profile approve {first.id}")
    approved = capsys.readouterr().out
    assert '"status": "applied"' in approved
    assert "tone: concise" in ProfileStore(config.birkin_home(), {}).snapshot().documents["preferences"].entries

    sc.dispatch(restarted, f"/profile reject {second.id}")
    rejected = capsys.readouterr().out
    assert '"status": "rejected"' in rejected
    assert not restarted.memory.profile_actions().pending()


def test_approval_revalidates_stale_revision_and_refuses(capsys):
    session = _session(True)
    actions = session.memory.profile_actions()
    staged = actions.submit(ProfileEdit("preferences", "add", content="first"), trusted=True, source="test")
    ProfileStore(config.birkin_home(), {}).apply(ProfileEdit("preferences", "add", content="external"))

    sc.dispatch(_session(True), f"/profile approve {staged.id}")
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["error"]["type"] == "stale_revision"
    assert "first" not in ProfileStore(config.birkin_home(), {}).snapshot().documents["preferences"].entries


def test_malformed_profile_enabled_is_rejected():
    (config.birkin_home() / "config.json").write_text(
        json.dumps({"profile": {"enabled": "yes"}}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="profile.enabled must be boolean"):
        config.load_config()


def test_persona_promote_is_idempotent(capsys):
    session = _session(False)
    store = ProfileStore(config.birkin_home(), {})
    store.apply(ProfileEdit("mask", "add", content="Use short sentences."))
    sc.dispatch(session, "/persona promote")
    sc.dispatch(session, "/persona promote")
    from birkin import persona
    text = persona.read_soul()
    assert text.count("Use short sentences.") == 1
    assert "Promoted" in capsys.readouterr().out
