"""Orphan-process reaper: reaps only children of DEAD owners (procreg)."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest


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
    store._write_json(
        p,
        {
            "owner": 424242,
            "children": [501, 502],
            "records": [
                {"pid": 501, "process_generation": "generation-501"},
                {"pid": 502, "process_generation": "generation-502"},
            ],
        },
    )
    monkeypatch.setattr(
        procreg,
        "process_generation",
        lambda pid: f"generation-{pid}",
    )
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
    store._write_json(
        p,
        {
            "owner": 424243,
            "children": [601, 602],
            "records": [
                {"pid": 601, "process_generation": "generation-601"},
                {"pid": 602, "process_generation": "generation-602"},
            ],
        },
    )
    monkeypatch.setattr(
        procreg,
        "process_generation",
        lambda pid: f"generation-{pid}",
    )
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_posix_reaper_kills_registered_process_group(
    tmp_path,
    monkeypatch,
) -> None:
    procreg = _setup(tmp_path, monkeypatch)
    groups = []
    pids = []
    monkeypatch.setattr(
        procreg,
        "kill_process_group",
        lambda pid: groups.append(pid) or True,
    )
    monkeypatch.setattr(procreg.os, "kill", lambda pid, _sig: pids.append(pid))

    procreg._kill_pid(4312)

    assert groups == [4312]
    assert pids == []


def test_windows_reaper_uses_taskkill_for_registered_tree(
    tmp_path,
    monkeypatch,
) -> None:
    procreg = _setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(procreg.os, "name", "nt")
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setattr(
        procreg.subprocess,
        "run",
        lambda argv, **kwargs: calls.append((argv, kwargs)),
    )

    procreg._kill_pid(4312)

    assert calls == [
        (
            [
                r"C:\Windows\System32\taskkill.exe",
                "/F",
                "/T",
                "/PID",
                "4312",
            ],
            {"capture_output": True, "timeout": 10},
        )
    ]


def test_reaper_refuses_child_without_recorded_generation(
    tmp_path,
    monkeypatch,
) -> None:
    procreg = _setup(tmp_path, monkeypatch)
    from birkin import store

    path = procreg._reg_path(424244)
    store._write_json(
        path,
        {
            "owner": 424244,
            "owner_generation": "recorded-owner",
            "children": [701],
            "records": [{"pid": 701}],
        },
    )
    monkeypatch.setattr(
        procreg,
        "process_generation",
        lambda pid: f"current-{pid}",
    )
    killed: list[int] = []

    result = procreg.reap_orphans(
        alive=lambda pid: pid == 701,
        kill=killed.append,
    )

    assert result == {"dead_owners": 1, "killed": 0}
    assert killed == []


def test_kill_tree_resolves_windows_taskkill_absolutely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from birkin import proc

    calls = []
    handle = SimpleNamespace(
        pid=4312,
        kill=lambda: pytest.fail("absolute taskkill should succeed"),
    )
    monkeypatch.setattr(proc.os, "name", "nt")
    monkeypatch.setenv("SystemRoot", r"D:\Windows")
    monkeypatch.setattr(
        proc.subprocess,
        "run",
        lambda argv, **kwargs: (
            calls.append((argv, kwargs))
            or SimpleNamespace(returncode=0)
        ),
    )

    proc.kill_tree(handle)

    assert calls == [
        (
            [
                r"D:\Windows\System32\taskkill.exe",
                "/F",
                "/T",
                "/PID",
                "4312",
            ],
            {
                "capture_output": True,
                "timeout": 10,
                "check": False,
            },
        )
    ]


def test_windows_tree_kill_never_guesses_systemroot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from birkin import proc

    killed: list[bool] = []
    handle = SimpleNamespace(
        pid=4312,
        kill=lambda: killed.append(True),
    )
    monkeypatch.setattr(proc.os, "name", "nt")
    monkeypatch.delenv("SystemRoot", raising=False)
    monkeypatch.setattr(
        proc.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail(
            "missing SystemRoot fell back to PATH or a guessed directory"
        ),
    )

    proc.kill_tree(handle)

    assert killed == [True]


def test_register_sanitizes_and_replaces_generation_record(
    tmp_path,
    monkeypatch,
) -> None:
    procreg = _setup(tmp_path, monkeypatch)
    from birkin import store

    owner = 424242
    path = procreg._reg_path(owner)
    store._write_json(
        path,
        {
            "version": 2,
            "owner": owner,
            "owner_generation": "owner-generation",
            "children": [True, "invalid", 55],
            "records": [
                {"pid": 55, "process_generation": "stale"},
                "invalid",
                {"pid": 66, "process_generation": "generation-66"},
            ],
        },
    )
    monkeypatch.setattr(
        procreg,
        "process_generation",
        lambda pid: f"generation-{pid}",
    )
    deadline = datetime(2026, 8, 16, 7, 0, tzinfo=timezone.utc)

    procreg.register(
        55,
        owner=owner,
        session_id="computer-use",
        purpose="desktop-action",
        deadline=deadline,
    )

    data = store._read_json(path, None)
    assert data["children"] == [55]
    assert data["records"] == [
        {"pid": 66, "process_generation": "generation-66"},
        {
            "pid": 55,
            "process_generation": "generation-55",
            "session_id": "computer-use",
            "purpose": "desktop-action",
            "deadline": deadline.isoformat(),
        },
    ]
    updated = datetime.fromisoformat(data["updated"])
    assert updated.tzinfo is not None
    assert updated.utcoffset() == timezone.utc.utcoffset(updated)


def test_unregister_sanitizes_records_and_removes_empty_registry(
    tmp_path,
    monkeypatch,
) -> None:
    procreg = _setup(tmp_path, monkeypatch)
    from birkin import store

    owner = 424242
    path = procreg._reg_path(owner)
    store._write_json(
        path,
        {
            "version": 2,
            "owner": owner,
            "children": [True, "invalid", 55, 66],
            "records": [{"pid": 55}, "invalid", {"pid": 66}],
        },
    )

    procreg.unregister(55, owner=owner)

    data = store._read_json(path, None)
    assert data["children"] == [66]
    assert data["records"] == [{"pid": 66}]

    procreg.unregister(66, owner=owner)

    assert not path.exists()


def test_codex_sandbox_forced_in_argv():
    from birkin.codex_session import CodexAppServerSession, CodexSessionError
    s = CodexAppServerSession(model="gpt-5.6-sol")   # safe defaults
    argv = s._build_argv()
    assert 'sandbox_mode="workspace-write"' in argv
    assert 'approval_policy="never"' in argv
    assert "sandbox_workspace_write.network_access=false" in argv
    assert not any("danger-full-access" in a for a in argv)
    s.close()
    networked = CodexAppServerSession(
        model="gpt-5.6-sol", network_access=True)
    assert "sandbox_workspace_write.network_access=true" in (
        networked._build_argv())
    networked.close()
    full = CodexAppServerSession(model="gpt-5.6-sol",
                                 sandbox_mode="danger-full-access")
    assert 'sandbox_mode="danger-full-access"' in full._build_argv()
    full.close()
    bad = CodexAppServerSession(model="gpt-5.6-sol", sandbox_mode="yolo")
    with pytest.raises(CodexSessionError):
        bad._build_argv()


@pytest.mark.parametrize(
    ("operation", "child_pid"),
    [("register", 222), ("unregister", 111)],
)
def test_busy_registry_lock_is_best_effort(
        tmp_path, monkeypatch, operation, child_pid):
    procreg = _setup(tmp_path, monkeypatch)
    from birkin import store

    path = procreg._reg_path(424242)
    store._write_json(path, {"owner": 424242, "children": [111]})
    before = (path.exists(), path.read_bytes())
    armed = []

    class BusyLock:
        def __enter__(self):
            raise store.FileLockTimeout("busy")

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(store, "file_lock", lambda _path: BusyLock())
    monkeypatch.setattr(procreg, "_atexit_armed", False)
    monkeypatch.setattr(procreg.atexit, "register", armed.append)

    getattr(procreg, operation)(child_pid, owner=424242)

    assert (path.exists(), path.read_bytes()) == before
    assert armed == []
    assert procreg._atexit_armed is False
