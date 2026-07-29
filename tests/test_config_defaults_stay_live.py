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

import json

import pytest

from birkin import config


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    return config.config_path()


def _written(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def test_round_trip_preserves_the_effective_config(cfg_path):
    """Pruning must not change what the program actually sees."""
    cfg = config.load_config()
    cfg["model"] = "round-trip"
    cfg["workspace_roots"] = [str(cfg_path.parent)]
    config.save_config(cfg)
    again = config.load_config()
    for key in config.DEFAULT_CONFIG:
        assert again[key] == cfg[key], f"{key} changed across a save/load"


def test_the_file_is_still_owner_only_and_atomic(cfg_path):
    """The security properties of the original write must survive."""
    import inspect
    src = inspect.getsource(config.save_config)
    assert "os.replace" in src, "lost the atomic swap"
    assert "0o600" in src, "lost the owner-only mode"
    assert ".tmp" in src
