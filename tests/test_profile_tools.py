from __future__ import annotations

import json
import os
import sys

import pytest

from birkin import config
from birkin.memory import VaultMemory
from birkin.profile_actions import ProfileActions
from birkin.rolefiles import ProfileEdit, ProfileStore
from birkin.tools import ToolContext, build_registry


def _cfg(enabled: bool, **profile):
    cfg = config.load_config()
    cfg["profile"] = {**cfg["profile"], "enabled": enabled, **profile}
    return cfg


def _registry(cfg):
    mem = VaultMemory(cfg)
    return mem, build_registry(ToolContext(cfg=cfg, client=None, cwd=config.birkin_home(), memory=mem), include={"memory"})


def test_remember_key_value_routes_to_profiles_when_enabled():
    cfg = _cfg(True)
    mem, reg = _registry(cfg)
    result = reg.execute("remember", {"key": "tone", "value": "concise"})
    assert not result.is_error
    assert "tone: concise" in ProfileStore(config.birkin_home(), {}).snapshot().documents["preferences"].entries
    assert not mem.list_notes()


def test_remember_key_value_routes_to_vault_when_disabled():
    cfg = _cfg(False)
    mem, reg = _registry(cfg)
    result = reg.execute("remember", {"key": "tone", "value": "concise"})
    assert not result.is_error
    assert any(note["type"] == "preference" for note in mem.list_notes())
    assert not (config.birkin_home() / "profile").exists()


def test_free_form_remember_still_writes_vault_fact():
    cfg = _cfg(True)
    mem, reg = _registry(cfg)
    result = reg.execute("remember", {"note": "the sky is blue", "title": "Sky"})
    assert not result.is_error
    assert any(note["title"] == "Sky" and note["type"] == "fact" for note in mem.list_notes())


def test_memory_write_note_preference_refused_while_enabled():
    cfg = _cfg(True)
    _mem, reg = _registry(cfg)
    result = reg.execute("memory_write_note", {"title": "P", "body": "b", "type": "preference"})
    assert result.is_error
    assert "profile_write" in str(result.content)


@pytest.mark.parametrize("secret", [
    "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "gho_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "ghu_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "ghs_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "ghr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "github_pat_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "AKIAAAAAAAAAAAAAAAAA",
    "ASIAAAAAAAAAAAAAAAAA",
    "xoxb-1234567890-ABCDEFGHIJ",
    "xoxp-1234567890-ABCDEFGHIJ",
    "xoxa-1234567890-ABCDEFGHIJ",
    "xoxr-1234567890-ABCDEFGHIJ",
    "xoxs-1234567890-ABCDEFGHIJ",
    "AIzaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"[:-1],
    "-----BEGIN RSA PRIVATE KEY-----",
])
def test_new_credential_shapes_are_rejected_and_not_staged(secret: str):
    actions = ProfileActions(ProfileStore(config.birkin_home(), {}), approval_required=True)
    receipt = actions.submit(ProfileEdit("preferences", "add", content=secret), trusted=True, source="test")
    assert receipt.status == "error"
    assert receipt.error and receipt.error["type"] == "invalid"
    assert actions.pending() == ()


def test_pending_queue_permissions_are_owner_only_on_posix():
    if sys.platform == "win32":
        pytest.skip("Windows ACLs are not set by os.chmod; only POSIX mode is asserted")
    actions = ProfileActions(ProfileStore(config.birkin_home(), {}), approval_required=True)
    receipt = actions.submit(ProfileEdit("preferences", "add", content="tone: concise"), trusted=True, source="test")
    assert receipt.status == "pending"
    root = config.birkin_home() / "profile"
    path = root / "pending-v1.json"
    assert (os.stat(root).st_mode & 0o777) == 0o700
    assert (os.stat(path).st_mode & 0o777) == 0o600


def test_untrusted_writes_rejected():
    actions = ProfileActions(ProfileStore(config.birkin_home(), {}), approval_required=False)
    receipt = actions.submit(ProfileEdit("preferences", "add", content="x"), trusted=False, source="test")
    assert receipt.status == "error"
    assert receipt.error == {"type": "untrusted"}


def test_budget_error_payload_carries_all_structured_fields_and_preserves_bytes():
    store = ProfileStore(config.birkin_home(), {"preferences": 12})
    actions = ProfileActions(store, approval_required=False)
    ok = actions.submit(ProfileEdit("preferences", "add", content="short"), trusted=True, source="test")
    assert ok.status == "applied"
    path = config.birkin_home() / "profile" / "preferences.md"
    before = path.read_bytes()
    receipt = actions.submit(ProfileEdit("preferences", "add", content="this is far too long"), trusted=True, source="test")
    assert receipt.status == "error"
    payload = receipt.payload()["error"]
    assert {"used", "limit", "required_reduction", "revision", "entries"} <= set(payload)
    assert payload["type"] == "budget_exceeded"
    assert path.read_bytes() == before
    assert json.dumps(receipt.payload())
