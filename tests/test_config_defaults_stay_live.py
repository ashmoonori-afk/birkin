"""config.json is the user's overrides, not a snapshot of a past DEFAULT_CONFIG.

save_config serialised whatever it was handed, and every caller hands it
load_config()'s result — which is DEFAULT_CONFIG merged with the file. So the
first save froze all 79 defaults into config.json, and from then on
`cfg.update(saved)` in load_config replayed those frozen values over any newer
default. Measured on the author's install before the fix: 84 keys on disk, of
which only 8 had ever been chosen by the user (provider, model, gateway_model,
gateway_reasoning_effort, cli_timeout, morpheus_provider, workspace_roots,
channels). The other 70+ were dump artifacts that could never be improved
upstream — `birkin update` would pull new code and the old values would win,
silently, with no warning and no `birkin config` to inspect it.

The fix keeps the file to what actually differs. Keys birkin does not know
about are preserved untouched — legacy names, forward-compat keys, and
anything a user hand-added are none of save_config's business.
"""

from __future__ import annotations

import copy
import json

import pytest

from birkin import config
from tests.test_native_private_storage import assert_owner_only


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    return config.config_path()


def _written(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_new_install_defaults_to_codex_cli_oauth():
    assert config.DEFAULT_CONFIG["provider"] == "codex-cli"
    assert config.DEFAULT_CONFIG["model"] == "default"
    assert config.DEFAULT_CONFIG["subagent_model"] == "default"
    assert config.get_api_key(config.DEFAULT_CONFIG) == "cli"


def test_cli_network_access_default_and_override_validation(cfg_path):
    assert config.DEFAULT_CONFIG["cli_network_access"] is False
    assert config.DEFAULT_CONFIG["egress"]["enforced"] is True

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        json.dumps({"cli_network_access": False}), encoding="utf-8")
    assert config.load_config()["cli_network_access"] is False

    cfg_path.write_text(
        json.dumps({"cli_network_access": "false"}), encoding="utf-8")
    with pytest.warns(RuntimeWarning, match="cli_network_access"):
        assert config.load_config()["cli_network_access"] is False


def test_untouched_defaults_are_not_written(cfg_path):
    """The whole bug: saving one setting used to pin all the others."""
    cfg = dict(config.DEFAULT_CONFIG)
    cfg["model"] = "my-model"
    config.save_config(cfg)

    on_disk = _written(cfg_path)
    assert on_disk == {"model": "my-model"}, (
        f"save wrote {len(on_disk)} keys; only the changed one belongs")


def test_a_changed_value_is_written(cfg_path):
    cfg = {**config.DEFAULT_CONFIG, "max_turns": 99}
    config.save_config(cfg)
    assert _written(cfg_path)["max_turns"] == 99


def test_a_later_default_change_reaches_an_existing_install(cfg_path, monkeypatch):
    """The outcome the whole fix exists for."""
    cfg = {**config.DEFAULT_CONFIG, "model": "mine"}
    config.save_config(cfg)

    # birkin ships a new default for a key the user never touched.
    monkeypatch.setitem(config.DEFAULT_CONFIG, "max_turns", 48)
    loaded = config.load_config()
    assert loaded["max_turns"] == 48, "the install is pinned to a stale default"
    assert loaded["model"] == "mine", "the user's own choice was lost"


def test_keys_birkin_does_not_know_are_preserved(cfg_path):
    """Legacy names, forward-compat keys, hand-added ones — not ours to drop."""
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"nightly_hour": 3, "my_own_key": "x"}),
                        encoding="utf-8")
    cfg = config.load_config()
    cfg["model"] = "m"
    config.save_config(cfg)

    on_disk = _written(cfg_path)
    assert on_disk.get("nightly_hour") == 3
    assert on_disk.get("my_own_key") == "x"


def test_a_secret_is_still_written(cfg_path):
    """api_key defaults to None, so a real key differs and must survive."""
    cfg = {**config.DEFAULT_CONFIG, "api_key": "sk-test"}
    config.save_config(cfg)
    assert _written(cfg_path)["api_key"] == "sk-test"


def test_a_value_set_back_to_the_default_stops_being_pinned(cfg_path):
    cfg = {**config.DEFAULT_CONFIG, "max_turns": 99}
    config.save_config(cfg)
    assert "max_turns" in _written(cfg_path)

    cfg["max_turns"] = config.DEFAULT_CONFIG["max_turns"]
    config.save_config(cfg)
    assert "max_turns" not in _written(cfg_path), (
        "back at the default, so it should follow the default again")


def test_nested_channels_only_records_the_difference(cfg_path):
    base = config.DEFAULT_CONFIG.get("channels")
    if not isinstance(base, dict):
        pytest.skip("channels is not a nested default here")
    cfg = config.load_config()
    config.save_config(cfg)
    assert "channels" not in _written(cfg_path), (
        "an untouched nested default was pinned")


def test_only_the_changed_nested_keys_are_written(cfg_path):
    """A top-level-only diff pinned the sub-keys too. Enabling Telegram the way
    onboarding does wrote channels.http.enabled,
    channels.telegram.allowed_chat_ids and channels.telegram.stream — three
    values nobody chose, one level below the bug a3fc969 set out to kill."""
    cfg = config.load_config()
    cfg["channels"]["telegram"]["enabled"] = True
    cfg["channels"]["telegram"]["token"] = "T"
    config.save_config(cfg)

    written = _written(cfg_path)["channels"]
    assert written == {"telegram": {"enabled": True, "token": "T"}}, (
        f"nested defaults pinned: {written}")


def test_a_fully_default_subtree_is_omitted_entirely(cfg_path):
    cfg = config.load_config()
    cfg["model"] = "m"
    config.save_config(cfg)
    assert "channels" not in _written(cfg_path)


def test_nested_round_trip_is_lossless(cfg_path):
    cfg = config.load_config()
    cfg["channels"]["telegram"]["enabled"] = True
    cfg["channels"]["telegram"]["allowed_chat_ids"] = ["42"]
    config.save_config(cfg)
    again = config.load_config()
    assert again["channels"] == cfg["channels"]


def test_round_trip_preserves_the_effective_config(cfg_path):
    """Pruning must not change what the program actually sees."""
    cfg = config.load_config()
    cfg["model"] = "round-trip"
    cfg["workspace_roots"] = [str(cfg_path.parent)]
    config.save_config(cfg)
    again = config.load_config()
    for key in config.DEFAULT_CONFIG:
        assert again[key] == cfg[key], f"{key} changed across a save/load"


def test_saved_overrides_remain_owner_only(cfg_path):
    # Given: one non-default override.
    # When: the override is persisted.
    path = config.save_config({**config.DEFAULT_CONFIG, "model": "owner-only"})

    # Then: the final file remains owner-only on the active platform.
    assert path == cfg_path
    assert_owner_only(path, posix_mode=0o600)


# -- load_config must never hand out the global defaults -------------------

def test_a_loaded_config_cannot_mutate_the_global_defaults(cfg_path):
    """load_config did a SHALLOW dict(DEFAULT_CONFIG), so every caller got the
    same nested objects and one

        cfg["channels"]["telegram"]["allowed_chat_ids"] = ["c1"]

    rewrote the process-wide default for everyone loading afterwards. Six test
    sites do exactly that, and gateway trust is decided from that list — so a
    later load saw an allowlisted (trusted) Telegram where the config said
    open. It was masked only because config.json used to be a full dump, which
    made load_config take its rebuild-the-subtree branch every time; pruning
    the file to real overrides exposed it."""
    from birkin import config as c
    before = copy.deepcopy(c.DEFAULT_CONFIG["channels"])
    cfg = c.load_config()
    cfg["channels"]["telegram"]["allowed_chat_ids"] = ["POLLUTED"]
    assert c.DEFAULT_CONFIG["channels"] == before, (
        "a loaded config rewrote DEFAULT_CONFIG for the whole process")
    assert c.load_config()["channels"]["telegram"]["allowed_chat_ids"] != ["POLLUTED"]


def test_two_loads_do_not_share_nested_objects(cfg_path):
    from birkin import config as c
    a, b = c.load_config(), c.load_config()
    assert a["channels"] is not b["channels"]
    assert a["channels"] is not c.DEFAULT_CONFIG["channels"]
