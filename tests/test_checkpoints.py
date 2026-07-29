"""Shadow-git checkpoints: snapshot before mutation, restore on demand."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from birkin import checkpoints
from birkin.tools import ToolContext, ToolRegistry, Tool, ToolResult, build_registry

pytestmark = pytest.mark.skipif(shutil.which("git") is None,
                                reason="git is not installed")


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    yield


@pytest.fixture
def work(tmp_path):
    d = tmp_path / "project"
    d.mkdir()
    (d / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (d / "main.py").write_text("print('original')\n", encoding="utf-8")
    return d


def _mgr(**kw):
    return checkpoints.CheckpointManager(**kw)


# -- snapshots -------------------------------------------------------------

def test_snapshot_and_restore_round_trip(work):
    mgr = _mgr()
    assert mgr.ensure_checkpoint(work, "before edit")

    (work / "main.py").write_text("print('BROKEN')\n", encoding="utf-8")
    entries = mgr.list_checkpoints(work)
    assert len(entries) == 1 and entries[0]["reason"] == "before edit"

    ok, _ = mgr.restore(work, entries[0]["hash"])
    assert ok
    assert (work / "main.py").read_text(encoding="utf-8") == "print('original')\n"


def test_restore_reports_when_safety_snapshot_fails(work, monkeypatch):
    # Given: a valid rollback target, but no way to protect the current state.
    manager = _mgr()
    commit = manager.ensure_checkpoint(work, "before edit")
    assert commit
    target = work / "main.py"
    target.write_text("print('changed')\n", encoding="utf-8")
    monkeypatch.setattr(
        manager, "_take",
        lambda *args, **kwargs: (
            _ for _ in ()).throw(OSError("disk full")))

    # When: rollback tries to take its mandatory undo checkpoint.
    ok, message = manager.restore(work, commit)

    # Then: the tuple API reports failure and no rollback occurs.
    assert not ok
    assert "disk full" in message
    assert target.read_text(encoding="utf-8") == "print('changed')\n"


def test_nothing_is_written_into_the_users_project(work):
    mgr = _mgr()
    mgr.ensure_checkpoint(work, "snap")
    assert not (work / ".git").exists()
    assert sorted(p.name for p in work.iterdir()) == ["main.py", "pyproject.toml"]


def test_an_existing_git_repo_is_left_untouched(work):
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    import os
    e = {**os.environ, **env}
    subprocess.run(["git", "init", "-q"], cwd=work, env=e, capture_output=True)
    subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=work, env=e)
    subprocess.run(["git", "config", "user.name", "t"], cwd=work, env=e)
    subprocess.run(["git", "add", "-A"], cwd=work, env=e, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "theirs"], cwd=work, env=e,
                   capture_output=True)
    before = subprocess.run(["git", "log", "--format=%s"], cwd=work, env=e,
                            capture_output=True, text=True).stdout

    _mgr().ensure_checkpoint(work, "snap")

    after = subprocess.run(["git", "log", "--format=%s"], cwd=work, env=e,
                           capture_output=True, text=True).stdout
    assert before == after, "the user's own history must not change"
    status = subprocess.run(["git", "status", "--porcelain"], cwd=work, env=e,
                            capture_output=True, text=True).stdout
    assert status.strip() == "", "the user's working tree must stay clean"


def test_unchanged_workspace_costs_nothing(work):
    mgr = _mgr()
    assert mgr.ensure_checkpoint(work, "first")
    mgr.new_turn()
    assert mgr.ensure_checkpoint(work, "second") is None
    assert len(mgr.list_checkpoints(work)) == 1


def test_one_snapshot_per_workspace_per_turn(work):
    mgr = _mgr()
    assert mgr.ensure_checkpoint(work, "a")
    (work / "main.py").write_text("changed\n", encoding="utf-8")
    assert mgr.ensure_checkpoint(work, "b") is None, "same turn — deduped"
    mgr.new_turn()
    assert mgr.ensure_checkpoint(work, "c")


def test_disabled_manager_does_nothing(work):
    mgr = _mgr(enabled=False)
    assert mgr.ensure_checkpoint(work, "x") is None
    assert mgr.list_checkpoints(work) == []


def test_refuses_to_snapshot_home_or_a_drive_root():
    mgr = _mgr()
    assert mgr.ensure_checkpoint(Path.home(), "no") is None
    assert mgr.ensure_checkpoint(Path(Path.cwd().anchor), "no") is None


def test_two_workspaces_keep_separate_histories(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        d.mkdir()
        (d / "f.txt").write_text(d.name, encoding="utf-8")
    mgr = _mgr()
    mgr.ensure_checkpoint(a, "for a")
    mgr.ensure_checkpoint(b, "for b")
    assert [e["reason"] for e in mgr.list_checkpoints(a)] == ["for a"]
    assert [e["reason"] for e in mgr.list_checkpoints(b)] == ["for b"]


def test_prune_keeps_only_the_newest(work):
    mgr = _mgr(keep=3)
    for i in range(6):
        mgr.new_turn()
        (work / "main.py").write_text(f"v{i}\n", encoding="utf-8")
        mgr.ensure_checkpoint(work, f"snap {i}")
    entries = mgr.list_checkpoints(work)
    assert len(entries) <= 3
    assert entries[0]["reason"] == "snap 5"


def test_excluded_paths_are_not_snapshotted(work):
    (work / "node_modules").mkdir()
    (work / "node_modules" / "big.js").write_text("x" * 100, encoding="utf-8")
    (work / ".env").write_text("SECRET=hunter2", encoding="utf-8")
    mgr = _mgr()
    commit = mgr.ensure_checkpoint(work, "snap")
    assert commit

    import os
    env = mgr._env(work)
    out = subprocess.run(["git", "ls-tree", "-r", "--name-only", commit],
                         env=env, capture_output=True, text=True).stdout
    assert "node_modules" not in out
    assert ".env" not in out, "secrets must never reach the checkpoint store"
    assert "main.py" in out


# -- restore semantics -----------------------------------------------------

def test_restore_takes_a_snapshot_first_so_it_is_undoable(work):
    mgr = _mgr()
    mgr.ensure_checkpoint(work, "original")
    (work / "main.py").write_text("newer work\n", encoding="utf-8")

    first = mgr.list_checkpoints(work)[-1]["hash"]
    mgr.restore(work, first)
    reasons = [e["reason"] for e in mgr.list_checkpoints(work)]
    assert "before rollback" in reasons
    assert (work / "main.py").read_text(encoding="utf-8") == "print('original')\n"

    # And the newer work is recoverable from that pre-rollback snapshot.
    undo = next(e for e in mgr.list_checkpoints(work)
                if e["reason"] == "before rollback")
    mgr.restore(work, undo["hash"])
    assert (work / "main.py").read_text(encoding="utf-8") == "newer work\n"


def test_restore_a_single_file(work):
    (work / "other.py").write_text("keep me\n", encoding="utf-8")
    mgr = _mgr()
    mgr.ensure_checkpoint(work, "snap")
    (work / "main.py").write_text("bad\n", encoding="utf-8")
    (work / "other.py").write_text("also changed\n", encoding="utf-8")

    h = mgr.list_checkpoints(work)[-1]["hash"]
    ok, _ = mgr.restore(work, h, "main.py")
    assert ok
    assert (work / "main.py").read_text(encoding="utf-8") == "print('original')\n"
    assert (work / "other.py").read_text(encoding="utf-8") == "also changed\n"


def test_restore_rejects_bad_ids_and_paths(work):
    mgr = _mgr()
    mgr.ensure_checkpoint(work, "snap")
    h = mgr.list_checkpoints(work)[0]["hash"]
    assert mgr.restore(work, "--upload-pack=evil")[0] is False
    assert mgr.restore(work, "zzz")[0] is False
    assert mgr.restore(work, h, "../../etc/passwd")[0] is False
    assert mgr.restore(work, h, "/etc/passwd")[0] is False


def test_diff_shows_what_changed(work):
    mgr = _mgr()
    mgr.ensure_checkpoint(work, "snap")
    (work / "main.py").write_text("print('changed')\n", encoding="utf-8")
    text = mgr.diff(work, mgr.list_checkpoints(work)[0]["hash"])
    assert "main.py" in text and "changed" in text


# -- the preflight hook ----------------------------------------------------

def _ctx(work, **kw):
    cfg = {"shell_approval": "off", "spill_threshold": 0}
    cfg.update(kw.pop("cfg", {}))
    return ToolContext(cfg=cfg, client=None, cwd=work,
                       checkpoints=kw.pop("mgr", _mgr()))


def test_write_file_is_checkpointed_and_undoable(work):
    ctx = _ctx(work)
    reg = build_registry(ctx, include={"files"})
    reg.execute("write_file", {"path": "main.py", "content": "destroyed\n"})

    assert (work / "main.py").read_text(encoding="utf-8") == "destroyed\n"
    entries = ctx.checkpoints.list_checkpoints(work)
    assert entries and "write_file" in entries[0]["reason"]

    ctx.checkpoints.restore(work, entries[0]["hash"])
    assert (work / "main.py").read_text(encoding="utf-8") == "print('original')\n"


def test_destructive_shell_is_checkpointed(work):
    ctx = _ctx(work)
    reg = build_registry(ctx, include={"shell"})
    reg.execute("run_shell", {"command": "rm -rf junk", "timeout": 20})
    entries = ctx.checkpoints.list_checkpoints(work)
    assert entries and "run_shell" in entries[0]["reason"]


def test_benign_shell_is_not_checkpointed(work):
    ctx = _ctx(work)
    reg = build_registry(ctx, include={"shell"})
    reg.execute("run_shell", {"command": "echo hello", "timeout": 20})
    assert ctx.checkpoints.list_checkpoints(work) == []


def test_reads_are_not_checkpointed(work):
    ctx = _ctx(work)
    reg = build_registry(ctx, include={"files"})
    reg.execute("read_file", {"path": "main.py"})
    reg.execute("list_files", {"path": "."})
    assert ctx.checkpoints.list_checkpoints(work) == []


def test_a_failing_checkpoint_blocks_the_tool(work, monkeypatch):
    # Given: the required pre-mutation snapshot cannot be persisted.
    original = (work / "main.py").read_text(encoding="utf-8")
    ctx = _ctx(work)
    monkeypatch.setattr(ctx.checkpoints, "_take",
                        lambda *a, **k: (
                            _ for _ in ()).throw(OSError("disk full")))
    reg = build_registry(ctx, include={"files"})

    # When: a mutating tool reaches the registry boundary.
    res = reg.execute(
        "write_file", {"path": "main.py", "content": "must not write\n"})

    # Then: the mutation is refused and the workspace remains recoverable.
    assert res.is_error
    assert "checkpoint" in res.content.lower()
    assert "disk full" in res.content.lower()
    assert (work / "main.py").read_text(encoding="utf-8") == original


def test_no_manager_means_no_hook(work):
    ctx = ToolContext(cfg={"spill_threshold": 0}, client=None, cwd=work)
    reg = build_registry(ctx, include={"files"})
    res = reg.execute("write_file", {"path": "main.py", "content": "fine\n"})
    assert not res.is_error


def test_project_root_walks_up_to_the_marker(work):
    nested = work / "src" / "deep"
    nested.mkdir(parents=True)
    assert checkpoints.project_root_for(nested / "x.py") == work
