"""Orphan-process reaper: reaps only children of DEAD owners (procreg)."""

from __future__ import annotations

import os


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import procreg
    return procreg


def test_register_unregister_roundtrip(tmp_path, monkeypatch):
    procreg = _setup(tmp_path, monkeypatch)
    procreg.register(111)
    procreg.register(222)
    from birkin import store
    data = store._read_json(procreg._reg_path(), None)
    assert data["owner"] == os.getpid()
    assert set(data["children"]) == {111, 222}
    procreg.unregister(111)
    data = store._read_json(procreg._reg_path(), None)
    assert data["children"] == [222]
    procreg.unregister(222)                     # last child -> file removed
    assert not procreg._reg_path().exists()


def test_reaper_spares_live_owner(tmp_path, monkeypatch):
    procreg = _setup(tmp_path, monkeypatch)
    procreg.register(999, owner=os.getpid())    # a LIVE owner (this process)
    killed = []
    r = procreg.reap_orphans(alive=lambda pid: True,   # everyone alive
                             kill=killed.append)
    assert r == {"dead_owners": 0, "killed": 0}
    assert killed == []                         # live owner untouched
    assert procreg._reg_path().exists()         # registry kept


def test_reaper_kills_children_of_dead_owner(tmp_path, monkeypatch):
    procreg = _setup(tmp_path, monkeypatch)
    from birkin import store
    # a registry owned by a (fake) dead pid with two live children
    p = procreg._reg_path(424242)
    store._write_json(p, {"owner": 424242, "children": [501, 502]})
    killed = []

    def alive(pid):
        return pid != 424242                    # owner dead, children alive
    r = procreg.reap_orphans(alive=alive, kill=killed.append)
    assert r == {"dead_owners": 1, "killed": 2}
    assert sorted(killed) == [501, 502]
    assert not p.exists()                        # registry cleaned up


def test_reaper_skips_already_dead_children(tmp_path, monkeypatch):
    procreg = _setup(tmp_path, monkeypatch)
    from birkin import store
    p = procreg._reg_path(424243)
    store._write_json(p, {"owner": 424243, "children": [601, 602]})
    killed = []
    # owner dead; child 601 already gone, 602 still alive
    r = procreg.reap_orphans(alive=lambda pid: pid == 602, kill=killed.append)
    assert killed == [602] and r["killed"] == 1  # don't kill a reused/dead pid


def test_reaper_clears_corrupt_registry(tmp_path, monkeypatch):
    procreg = _setup(tmp_path, monkeypatch)
    bad = procreg._runs_dir() / "procreg-777.json"
    bad.write_text("{not json", encoding="utf-8")
    r = procreg.reap_orphans(alive=lambda pid: False, kill=lambda p: None)
    assert not bad.exists() and r["killed"] == 0


def test_pid_alive_current_process_true(tmp_path, monkeypatch):
    procreg = _setup(tmp_path, monkeypatch)
    assert procreg.pid_alive(os.getpid()) is True
    assert procreg.pid_alive(0) is False
    assert procreg.pid_alive(None) is False
    assert procreg.pid_alive(-5) is False
