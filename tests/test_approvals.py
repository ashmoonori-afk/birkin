from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import partial
from inspect import Parameter, signature
from pathlib import Path

import pytest

from birkin import approval_execution, approvals, cron, store


def test_is_auto():
    cfg = {"auto_approve": ["memory", "skills"]}
    assert approvals.is_auto("memory", cfg) is True
    assert approvals.is_auto("cron", cfg) is False


def test_propose_auto_category_applies_immediately():
    cfg = {"auto_approve": ["memory", "skills"]}
    res = approvals.propose(
        category="memory", title="t", description="", payload={}, cfg=cfg
    )
    assert res["auto"] is True
    assert store.list_pending() == []
    assert store.get_pending(res["id"])["status"] == "approved"


def test_propose_consequential_is_queued():
    cfg = {"auto_approve": ["memory", "skills"]}
    res = approvals.propose(
        category="cron",
        title="Digest",
        description="d",
        payload={
            "name": "digest",
            "hour": 9,
            "minute": 0,
            "type": "prompt",
            "value": "go",
        },
        cfg=cfg,
    )
    assert res["auto"] is False
    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0]["title"] == "Digest"


def test_public_resolution_api_requires_explicit_identity() -> None:
    required = {
        approvals.approve: ("approved_by", "approved_via"),
        approvals.reject: ("rejected_by", "rejected_via"),
        approvals.claim: ("approved_by", "approved_via"),
        approval_execution.approve: ("approved_by", "approved_via"),
        approval_execution.reject: ("rejected_by", "rejected_via"),
        approval_execution.claim: ("approved_by", "approved_via"),
    }
    for resolver, parameters in required.items():
        resolver_signature = signature(resolver)
        assert all(
            resolver_signature.parameters[name].default is Parameter.empty
            for name in parameters
        )


def test_low_level_claim_rejects_empty_identity() -> None:
    with pytest.raises(ValueError, match="identity must be non-empty"):
        _ = approval_execution.claim(
            "0123456789ab",
            approved_by="",
            approved_via="test",
        )


def test_low_level_approve_rejects_empty_identity() -> None:
    with pytest.raises(ValueError, match="identity must be non-empty"):
        _ = approval_execution.approve(
            "0123456789ab",
            approved_by="human:test",
            approved_via=" ",
        )


def test_low_level_reject_rejects_empty_identity() -> None:
    with pytest.raises(ValueError, match="identity must be non-empty"):
        _ = approval_execution.reject(
            "0123456789ab",
            rejected_by=" ",
            rejected_via="test",
        )


def test_facade_approval_uses_helper_unless_shell_runner_is_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executors = []

    def resolve(_approval_id, executor=None, **_kwargs):
        executors.append(executor)
        return {"ok": True}

    monkeypatch.setattr(approval_execution, "approve", resolve)

    assert approvals.approve(
        "0123456789ab",
        approved_by="human:test",
        approved_via="test",
    ) == {"ok": True}
    monkeypatch.setattr(approvals, "run_shell_command", lambda _request: None)
    assert approvals.approve(
        "0123456789ab",
        approved_by="human:test",
        approved_via="test",
    ) == {"ok": True}

    assert executors == [None, approvals.execute_action]


def test_failed_auto_skill_proposal_is_audited_as_error():
    cfg = {"auto_approve": ["skill"]}
    res = approvals.propose(
        category="skill",
        title="stale",
        description="",
        payload={"action": "improve", "target": "missing-skill", "addition": "note"},
        cfg=cfg,
    )
    assert res["auto"] is True and res["ok"] is False
    assert store.get_pending(res["id"])["status"] == "error"


def test_approve_executes_and_clears():
    cfg = {"auto_approve": ["memory", "skills"]}
    approvals.propose(
        category="cron",
        title="Digest",
        description="d",
        payload={
            "name": "digest",
            "hour": 9,
            "minute": 0,
            "type": "prompt",
            "value": "go",
        },
        cfg=cfg,
    )
    pid = store.list_pending()[0]["id"]
    res = approvals.approve(pid, approved_by="human:test", approved_via="test")
    assert res["ok"] is True
    assert store.list_pending() == []
    jobs = cron.load_jobs()
    assert any(j["name"] == "digest" for j in jobs)


def test_reject_clears_without_executing():
    cfg = {"auto_approve": []}
    approvals.propose(
        category="cron",
        title="X",
        description="",
        payload={"name": "x", "hour": 1, "minute": 0},
        cfg=cfg,
    )
    pid = store.list_pending()[0]["id"]
    assert approvals.reject(pid, rejected_by="human:test", rejected_via="test")["ok"] is True
    assert store.list_pending() == []
    assert cron.load_jobs() == []


def test_structured_action_round_trip():
    result = approvals.request_answers(
        title="Deploy release",
        description="Choose the deployment target and verification scope.",
        questions=[
            {
                "id": "target",
                "text": "Where should Birkin deploy?",
                "options": [
                    {"value": "staging", "label": "Staging"},
                    {"value": "production", "label": "Production"},
                ],
                "recommended": "staging",
            },
            {
                "id": "checks",
                "text": "Which checks should run?",
                "options": [
                    {"value": "unit", "label": "Unit tests"},
                    {"value": "integration", "label": "Integration tests"},
                ],
                "multiple": True,
            },
        ],
        origin="test",
        timeout_seconds=300,
    )

    pending = store.get_pending(result["id"])
    assert pending is not None
    assert pending["action_state"] == "action_needed"
    assert pending["questions"][0]["recommended"] == "staging"

    resolved = approvals.answer(
        result["id"],
        answers={"target": "staging", "checks": ["unit", "integration"]},
        source="web:test-user",
    )

    assert resolved == {
        "ok": True,
        "event": "action_resolved",
        "id": result["id"],
        "answers": {
            "target": "staging",
            "checks": ["unit", "integration"],
        },
        "resolved_by": "web:test-user",
    }
    record = store.get_pending(result["id"])
    assert record is not None
    assert record["action_state"] == "action_resolved"
    assert record["answers"] == resolved["answers"]
    assert record["resolved_by"] == "web:test-user"


def test_first_valid_answer_wins():
    action = approvals.request_answers(
        title="Pick target",
        description="",
        questions=[
            {
                "id": "target",
                "text": "Where?",
                "options": [
                    {"value": "staging", "label": "Staging"},
                    {"value": "production", "label": "Production"},
                ],
            }
        ],
        origin="test",
    )

    def respond(source: str, target: str):
        return approvals.answer(action["id"], answers={"target": target}, source=source)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda item: respond(*item),
                [("web:first", "staging"), ("telegram:second", "production")],
            )
        )

    assert sorted(result["event"] for result in results) == [
        "action_resolved",
        "reply_rejected",
    ]
    record = store.get_pending(action["id"])
    assert record is not None
    assert record["resolved_by"] in {"web:first", "telegram:second"}
    winning_target = "staging" if record["resolved_by"] == "web:first" else "production"
    assert record["answers"] == {"target": winning_target}


def test_concurrent_shell_approval_executes_exactly_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = []

    class Result:
        returncode = 0
        stdout = "approved"
        stderr = ""

    def run(request):
        calls.append(request)
        return Result()

    monkeypatch.setattr(approvals, "run_shell_command", run)
    proposal = approvals.propose(
        category="shell",
        title="Run once",
        description="",
        payload={"command": "printf approved", "cwd": str(tmp_path)},
        cfg={"auto_approve": []},
    )

    def approve_once(_index: int) -> dict[str, object]:
        return approval_execution.approve(proposal["id"], approvals.execute_action, approved_by="human:test", approved_via="test")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                partial(
                    approvals.approve,
                    approved_by="human:test",
                    approved_via="test",
                ),
                [proposal["id"], proposal["id"]],
            )
        )

    assert sum(bool(result.get("ok")) for result in results) == 1
    assert len(calls) == 1
    assert store.get_pending(proposal["id"])["status"] == "approved"


def test_terminal_lease_approval_skips_placeholder_shell(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[object] = []

    def forbidden_runner(request: object) -> None:
        calls.append(request)
        raise AssertionError("terminal lease approval invoked the shell runner")

    monkeypatch.setattr(approvals, "run_shell_command", forbidden_runner)
    proposal = approvals.propose(
        category="shell",
        title="Native terminal shell access",
        description="Allow a Python-owned interactive shell for the native human.",
        payload={
            "command": "/usr/bin/true",
            "shell": "/bin/sh",
            "cwd": str(tmp_path),
            "terminal_lease_only": True,
            "session_id": "session-1",
            "actor_kind": "native_human",
        },
        cfg={"auto_approve": []},
        origin="native_human",
    )
    approval_id = proposal.get("id")
    assert isinstance(approval_id, str)

    result = approvals.approve(approval_id, approved_by="human:test", approved_via="test")

    assert result == {"ok": True, "result": "Approved native terminal lease."}
    assert calls == []
    record = store.get_pending(approval_id)
    assert record is not None
    assert record["status"] == "approved"


def test_forged_terminal_lease_marker_cannot_bypass_shell_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[object] = []

    def forbidden_runner(request: object) -> None:
        calls.append(request)
        raise AssertionError("forged terminal lease invoked the shell runner")

    monkeypatch.setattr(approvals, "run_shell_command", forbidden_runner)
    proposal = approvals.propose(
        category="shell",
        title="Forged terminal lease",
        description="",
        payload={
            "command": "touch escaped",
            "shell": "/bin/sh",
            "cwd": str(tmp_path),
            "terminal_lease_only": True,
            "session_id": "session-1",
            "actor_kind": "native_human",
        },
        cfg={"auto_approve": []},
    )
    approval_id = proposal.get("id")
    assert isinstance(approval_id, str)

    result = approvals.approve(approval_id, approved_by="human:test", approved_via="test")

    assert result == {
        "ok": False,
        "error": "action failed: invalid terminal lease approval payload",
    }
    assert calls == []
    record = store.get_pending(approval_id)
    assert record is not None
    assert record["status"] == "error"


def test_rejects_invalid_or_expired_answer():
    action = approvals.request_answers(
        title="Pick target",
        description="",
        questions=[
            {
                "id": "target",
                "text": "Where?",
                "options": [{"value": "staging", "label": "Staging"}],
            }
        ],
        origin="test",
    )
    invalid = approvals.answer(
        action["id"], answers={"target": "production"}, source="web:user"
    )
    assert invalid["event"] == "reply_rejected"
    pending = store.get_pending(action["id"])
    assert pending is not None
    assert pending["action_state"] == "action_needed"

    expired_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(
        timespec="seconds"
    )
    store.resolve_pending(
        action["id"],
        "pending",
        details={"expires_at": expired_at, "action_state": "action_needed"},
    )
    expired = approvals.answer(
        action["id"], answers={"target": "staging"}, source="web:user"
    )
    assert expired == {
        "ok": False,
        "event": "reply_rejected",
        "id": action["id"],
        "error": "action expired",
    }
    record = store.get_pending(action["id"])
    assert record is not None
    assert record["action_state"] == "action_expired"
    assert "answers" not in record


def test_structured_action_rejects_legacy_approval_bypass():
    action = approvals.request_answers(
        title="Pick target",
        description="",
        questions=[
            {
                "id": "target",
                "text": "Where?",
                "options": [{"value": "staging", "label": "Staging"}],
            }
        ],
        origin="test",
    )

    result = approvals.approve(action["id"], approved_by="human:test", approved_via="test")

    assert result == {
        "ok": False,
        "error": "structured action requires answers",
    }
    record = store.get_pending(action["id"])
    assert record is not None
    assert record["status"] == "pending"
    assert record["action_state"] == "action_needed"


def test_rejected_structured_action_cannot_be_answered():
    action = approvals.request_answers(
        title="Pick target",
        description="",
        questions=[
            {
                "id": "target",
                "text": "Where?",
                "options": [{"value": "staging", "label": "Staging"}],
            }
        ],
        origin="test",
    )
    assert approvals.reject(action["id"], rejected_by="human:test", rejected_via="test")["ok"] is True

    result = approvals.answer(
        action["id"], answers={"target": "staging"}, source="web:user"
    )

    assert result["event"] == "reply_rejected"
    record = store.get_pending(action["id"])
    assert record is not None
    assert record["status"] == "rejected"


def test_naive_expiry_and_non_string_answers_fail_closed():
    action = approvals.request_answers(
        title="Pick target",
        description="",
        questions=[
            {
                "id": "target",
                "text": "Where?",
                "options": [{"value": "1", "label": "One"}],
            }
        ],
        origin="test",
    )
    store.resolve_pending(
        action["id"],
        "pending",
        details={"expires_at": "2099-01-01T00:00:00"},
    )

    result = approvals.answer(action["id"], answers={"target": 1}, source="web:user")

    assert result == {
        "ok": False,
        "event": "reply_rejected",
        "id": action["id"],
        "error": "invalid action expiry",
    }


def test_resolve_pending_does_not_overwrite_core_fields():
    record = store.add_pending(
        category="question",
        title="Pick target",
        description="",
        payload={},
    )

    with pytest.raises(ValueError, match="pending details overwrite status"):
        store.resolve_pending(record["id"], "answered", details={"status": "pending"})


def test_execute_cron_clamps_and_defaults_clock(monkeypatch):
    # A cron payload may carry garbage ("9; rm") or out-of-range values (25, 999);
    # execute_action must default on garbage and clamp, never raise or store a
    # time that can't fire.
    captured = []
    monkeypatch.setattr(
        cron,
        "add_job",
        lambda **kw: (
            captured.append(kw)
            or {
                "id": "1",
                "name": kw["name"],
                "hour": kw["hour"],
                "minute": kw["minute"],
            }
        ),
    )
    approvals.execute_action("cron", {"name": "j", "hour": "9; rm", "minute": 999})
    assert captured[-1]["hour"] == 9 and captured[-1]["minute"] == 59
    approvals.execute_action("cron", {"name": "j", "hour": 25, "minute": -5})
    assert captured[-1]["hour"] == 23 and captured[-1]["minute"] == 0


def test_execute_action_unknown_category_raises():
    with pytest.raises(ValueError, match="unknown approval category"):
        approvals.execute_action("bogus", {})


def test_approved_checkpoint_restore_updates_canonical_session_state(
    tmp_path,
):
    from birkin import checkpoint_state, checkpoints, goals, harness

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "state.txt").write_text("stable\n", encoding="utf-8")
    session_id = "approval-restore"
    harness.update_working(session_id, decisions=["before"])
    goals.set_goal("before goal", session_id=session_id)
    manager = checkpoints.CheckpointManager(
        state_snapshot=lambda: checkpoint_state.snapshot(session_id),
        state_restore=lambda state: checkpoint_state.restore(
            session_id,
            state,
        ),
    )
    checkpoint = manager.ensure_checkpoint(workspace, "before")
    assert checkpoint
    harness.update_working(session_id, decisions=["after"])
    goals.set_goal("after goal", session_id=session_id)

    result = approvals.execute_action(
        "checkpoint_restore",
        {
            "workspace": str(workspace),
            "checkpoint": checkpoint,
            "mode": "task",
            "session_id": session_id,
        },
    )

    assert "task state" in result
    assert harness.working_state(session_id)["decisions"] == ["before"]
    restored_goal = goals.get_active(session_id=session_id)
    assert restored_goal is not None
    assert restored_goal.objective == "before goal"


def test_approved_checkpoint_restore_rejects_cross_session_state(
    tmp_path,
):
    from birkin import checkpoint_state, checkpoints, goals, harness

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "state.txt").write_text("stable\n", encoding="utf-8")
    source = "source-session"
    target = "target-session"
    harness.update_working(source, decisions=["source"])
    goals.set_goal("source goal", session_id=source)
    manager = checkpoints.CheckpointManager(
        state_snapshot=lambda: checkpoint_state.snapshot(source),
        state_restore=lambda state: checkpoint_state.restore(source, state),
    )
    checkpoint = manager.ensure_checkpoint(workspace, "source")
    assert checkpoint
    harness.update_working(target, decisions=["target"])
    goals.set_goal("target goal", session_id=target)

    with pytest.raises(ValueError, match="different session"):
        approvals.execute_action(
            "checkpoint_restore",
            {
                "workspace": str(workspace),
                "checkpoint": checkpoint,
                "mode": "task",
                "session_id": target,
            },
        )

    assert harness.working_state(target)["decisions"] == ["target"]
    target_goal = goals.get_active(session_id=target)
    assert target_goal is not None
    assert target_goal.objective == "target goal"


def test_cross_session_both_restore_rejects_before_file_mutation(
    tmp_path,
):
    from birkin import checkpoint_state, checkpoints, goals, harness

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_file = workspace / "state.txt"
    state_file.write_text("source\n", encoding="utf-8")
    source = "source-both-session"
    target = "target-both-session"
    harness.update_working(source, decisions=["source"])
    goals.set_goal("source goal", session_id=source)
    manager = checkpoints.CheckpointManager(
        state_snapshot=lambda: checkpoint_state.snapshot(source),
        state_restore=lambda state: checkpoint_state.restore(source, state),
    )
    checkpoint = manager.ensure_checkpoint(workspace, "source")
    assert checkpoint
    state_file.write_text("target\n", encoding="utf-8")
    harness.update_working(target, decisions=["target"])
    goals.set_goal("target goal", session_id=target)

    with pytest.raises(ValueError, match="different session"):
        approvals.execute_action(
            "checkpoint_restore",
            {
                "workspace": str(workspace),
                "checkpoint": checkpoint,
                "mode": "both",
                "session_id": target,
            },
        )

    assert state_file.read_text(encoding="utf-8") == "target\n"
    assert harness.working_state(target)["decisions"] == ["target"]


def test_checkpoint_state_rejects_malformed_goal_before_working_mutation(
    tmp_path,
    monkeypatch,
):
    from birkin import checkpoint_state, goals, harness

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    session_id = "transactional-state"
    harness.update_working(session_id, decisions=["current"])
    goals.set_goal("current goal", session_id=session_id)
    before_working = harness.working_state(session_id)
    before_goal = goals.get_active(session_id=session_id)

    with pytest.raises(ValueError, match="goal snapshot is malformed"):
        checkpoint_state.restore(
            session_id,
            {
                "session_id": session_id,
                "working_memory": {"decisions": ["restored"]},
                "goal": {"objective": 3},
            },
        )

    assert harness.working_state(session_id) == before_working
    assert goals.get_active(session_id=session_id) == before_goal


def test_execute_claimed_unknown_category_marks_error():
    rec = store.add_pending(
        category="bogus",
        title="Unknown",
        description="",
        payload={},
    )
    aid = rec["id"]
    assert approvals.claim(aid, approved_by="human:test", approved_via="test")["ok"] is True

    result = approvals.execute_claimed(aid)

    assert result["ok"] is False
    assert "unknown approval category" in result["error"]
    assert store.get_pending(aid)["status"] == "error"
