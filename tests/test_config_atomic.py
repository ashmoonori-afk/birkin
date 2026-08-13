"""save_config must write config.json atomically (it can hold the API key).

A crash mid-write must never truncate/corrupt the live config — the new value
is swapped in via os.replace() only after the temp file is fully written.
"""

from __future__ import annotations

import pytest

from birkin import config


def test_save_config_round_trips_and_leaves_no_tmp():
    config.save_config({**config.DEFAULT_CONFIG, "model": "sonnet"})
    p = config.config_path()
    assert p.exists()
    import json
    assert json.loads(p.read_text(encoding="utf-8"))["model"] == "sonnet"
    assert not list(p.parent.glob("config.json*.tmp"))  # temp cleaned up


def test_save_config_failure_keeps_original_intact(monkeypatch):
    # Write a good config, then make the atomic swap fail and assert the live
    # config.json is the ORIGINAL (not truncated) and no partial .tmp remains.
    config.save_config({**config.DEFAULT_CONFIG, "model": "good"})
    p = config.config_path()
    good = p.read_text(encoding="utf-8")

    def boom(src, dst):
        raise OSError("simulated crash during swap")

    monkeypatch.setattr(config.os, "replace", boom)
    with pytest.raises(OSError):
        config.save_config({**config.DEFAULT_CONFIG, "model": "bad"})

    assert p.read_text(encoding="utf-8") == good          # original intact
    assert not list(p.parent.glob("config.json*.tmp"))    # no partial tmp left


def test_save_config_creates_temp_owner_only(monkeypatch):
    real_open = config.os.open
    modes = []

    def recording_open(path, flags, mode=0o777):
        modes.append(mode)
        return real_open(path, flags, mode)

    monkeypatch.setattr(config.os, "open", recording_open)

    config.save_config({**config.DEFAULT_CONFIG, "model": "safe"})

    assert modes == [0o600]


def test_save_config_uses_unique_temp_siblings(monkeypatch):
    seen = []
    real_replace = config.os.replace

    def recording_replace(source, destination):
        seen.append(str(source))
        return real_replace(source, destination)

    monkeypatch.setattr(config.os, "replace", recording_replace)

    config.save_config({**config.DEFAULT_CONFIG, "model": "first"})
    config.save_config({**config.DEFAULT_CONFIG, "model": "second"})

    assert len(set(seen)) == 2
    assert all(str(config.os.getpid()) in path for path in seen)
    assert not list(config.config_path().parent.glob("config.json*.tmp"))
