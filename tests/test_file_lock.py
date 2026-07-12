"""#2: cross-process file lock protects cron.json read-modify-write."""

from __future__ import annotations


def test_file_lock_is_exclusive_and_reentrant_after_release(tmp_path):
    from birkin import store
    p = tmp_path / "x.json"
    with store.file_lock(p) as lk:
        assert lk._held is True
        assert (tmp_path / "x.json.lock").exists()
    assert not (tmp_path / "x.json.lock").exists()   # released
    with store.file_lock(p):                          # reacquire cleanly
        pass


def test_file_lock_times_out_and_proceeds_unlocked(tmp_path):
    from birkin import store
    p = tmp_path / "y.json"
    (tmp_path / "y.json.lock").write_text("")         # a fresh held lock
    # short timeout, non-stale -> proceeds unlocked rather than blocking forever
    with store.file_lock(p, timeout=0.15, stale=999) as lk:
        assert lk._held is False                      # didn't acquire, no wedge


def test_stale_lock_is_reclaimed(tmp_path):
    import os
    import time
    from birkin import store
    p = tmp_path / "z.json"
    lock = tmp_path / "z.json.lock"
    lock.write_text("")
    old = time.time() - 120
    os.utime(lock, (old, old))                        # 2 min old -> stale
    with store.file_lock(p, timeout=1.0, stale=30.0) as lk:
        assert lk._held is True                       # reclaimed the dead lock


def test_cron_ops_still_work_under_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import cron
    j = cron.add_job(name="r", hour=9, minute=0, action_type="prompt",
                     value="x", deliver_chat_id="42")
    assert cron.load_jobs()[0]["id"] == j["id"]
    cron.mark_ran(j["id"])
    assert cron.load_jobs()[0]["last_run"] is not None
    assert cron.remove_job(j["id"]) is True
    assert cron.load_jobs() == []
