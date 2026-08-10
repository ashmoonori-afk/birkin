"""Durable subagent run records and inbox delivery."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from birkin import agentruns, config


def test_register_get_heartbeat_and_finish_run():
    rec = agentruns.register_run("x" * 800, parent_id="parent")

    assert len(rec["id"]) == 12
    assert rec["parent_id"] == "parent"
    assert rec["status"] == "running"
    assert len(rec["task"]) == agentruns.TASK_MAX_CHARS
    assert rec["started_at"] == rec["last_heartbeat"]
    assert agentruns.get_run(rec["id"]) == rec

    old_heartbeat = rec["last_heartbeat"]
    updated = agentruns.heartbeat(rec["id"])
    assert updated is not None
    assert updated["last_heartbeat"] >= old_heartbeat

    result = "prefix-" + "z" * (agentruns.RESULT_TAIL_CHARS + 20)
    done = agentruns.finish_run(rec["id"], "done", result)
    assert done is not None
    assert done["status"] == "done"
    assert done["result"] == result[-agentruns.RESULT_TAIL_CHARS:]


def test_stale_running_run_is_reported_as_stale():
    rec = agentruns.register_run("slow task")
    path = config.agent_runs_dir() / f"{rec['id']}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["last_heartbeat"] = (
        datetime.now(timezone.utc) - timedelta(seconds=181)
    ).isoformat(timespec="seconds")
    path.write_text(json.dumps(raw), encoding="utf-8")

    listed = agentruns.list_runs()[0]
    assert listed["status"] == "stale"
    assert listed["stalled"] is True
    assert listed["heartbeat_age"] >= 180


def test_list_runs_builds_parent_child_tree_and_keeps_orphans():
    parent = agentruns.register_run("parent")
    child = agentruns.register_run("child", parent_id=parent["id"])
    orphan = agentruns.register_run("orphan", parent_id="missing")

    roots = agentruns.list_runs()
    by_id = {run["id"]: run for run in roots}
    assert parent["id"] in by_id
    assert orphan["id"] in by_id
    assert child["id"] not in by_id
    assert by_id[parent["id"]]["children"][0]["id"] == child["id"]


def test_append_and_drain_messages_consumes_in_order():
    run = agentruns.register_run("message target")
    assert agentruns.append_message(run["id"], " first ") is True
    assert agentruns.append_message(run["id"], "second") is True

    assert agentruns.drain_messages(run["id"]) == [" first ", "second"]
    assert agentruns.drain_messages(run["id"]) == []


def test_invalid_ids_do_not_escape_agent_runs_directory():
    assert agentruns.get_run("../config") is None
    assert agentruns.heartbeat("../config") is None
    assert agentruns.finish_run("../config", "done", "x") is None
    assert agentruns.append_message("../config", "x") is False
    assert agentruns.drain_messages("../config") == []


def test_finish_rejects_unknown_status():
    run = agentruns.register_run("status")
    try:
        agentruns.finish_run(run["id"], "cancelled", "")
    except ValueError as exc:
        assert "status" in str(exc)
    else:
        raise AssertionError("unknown status accepted")
