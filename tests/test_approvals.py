from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from birkin import approvals, cron, store


def test_is_auto():
    cfg = {"auto_approve": ["memory", "skills"]}
    assert approvals.is_auto("memory", cfg) is True
    assert approvals.is_auto("cron", cfg) is False


def test_propose_auto_category_applies_immediately():
    cfg = {"auto_approve": ["memory", "skills"]}
    res = approvals.propose(category="memory", title="t", description="",
                            payload={}, cfg=cfg)
    assert res["auto"] is True
    assert store.list_pending() == []
    assert store.get_pending(res["id"])["status"] == "approved"


def test_propose_consequential_is_queued():
    cfg = {"auto_approve": ["memory", "skills"]}
    res = approvals.propose(category="cron", title="Digest", description="d",
                            payload={"name": "digest", "hour": 9, "minute": 0,
                                     "type": "prompt", "value": "go"}, cfg=cfg)
    assert res["auto"] is False
    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0]["title"] == "Digest"


def test_failed_auto_skill_proposal_is_audited_as_error():
    cfg = {"auto_approve": ["skill"]}
    res = approvals.propose(
        category="skill", title="stale", description="",
        payload={"action": "improve", "target": "missing-skill",
                 "addition": "note"}, cfg=cfg)
    assert res["auto"] is True and res["ok"] is False
    assert store.get_pending(res["id"])["status"] == "error"


def test_approve_executes_and_clears():
    cfg = {"auto_approve": ["memory", "skills"]}
    approvals.propose(category="cron", title="Digest", description="d",
                      payload={"name": "digest", "hour": 9, "minute": 0,
                               "type": "prompt", "value": "go"}, cfg=cfg)
    pid = store.list_pending()[0]["id"]
    res = approvals.approve(pid)
    assert res["ok"] is True
    assert store.list_pending() == []
    jobs = cron.load_jobs()
    assert any(j["name"] == "digest" for j in jobs)


def test_reject_clears_without_executing():
    cfg = {"auto_approve": []}
    approvals.propose(category="cron", title="X", description="",
                      payload={"name": "x", "hour": 1, "minute": 0}, cfg=cfg)
    pid = store.list_pending()[0]["id"]
    assert approvals.reject(pid)["ok"] is True
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
        questions=[{
            "id": "target",
            "text": "Where?",
            "options": [
                {"value": "staging", "label": "Staging"},
                {"value": "production", "label": "Production"},
            ],
        }],
        origin="test",
    )

    def respond(source: str, target: str):
        return approvals.answer(
            action["id"], answers={"target": target}, source=source)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda item: respond(*item),
            [("web:first", "staging"), ("telegram:second", "production")],
        ))

    assert sorted(result["event"] for result in results) == [
        "action_resolved", "reply_rejected"]
    record = store.get_pending(action["id"])
    assert record is not None
    assert record["resolved_by"] in {"web:first", "telegram:second"}
    winning_target = (
        "staging" if record["resolved_by"] == "web:first" else "production")
    assert record["answers"] == {"target": winning_target}


def test_rejects_invalid_or_expired_answer():
    action = approvals.request_answers(
        title="Pick target",
        description="",
        questions=[{
            "id": "target",
            "text": "Where?",
            "options": [{"value": "staging", "label": "Staging"}],
        }],
        origin="test",
    )
    invalid = approvals.answer(
        action["id"], answers={"target": "production"}, source="web:user")
    assert invalid["event"] == "reply_rejected"
    pending = store.get_pending(action["id"])
    assert pending is not None
    assert pending["action_state"] == "action_needed"

    expired_at = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat(timespec="seconds")
    store.resolve_pending(
        action["id"],
        "pending",
        details={"expires_at": expired_at, "action_state": "action_needed"},
    )
    expired = approvals.answer(
        action["id"], answers={"target": "staging"}, source="web:user")
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
        questions=[{
            "id": "target",
            "text": "Where?",
            "options": [{"value": "staging", "label": "Staging"}],
        }],
        origin="test",
    )

    result = approvals.approve(action["id"])

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
        questions=[{
            "id": "target",
            "text": "Where?",
            "options": [{"value": "staging", "label": "Staging"}],
        }],
        origin="test",
    )
    assert approvals.reject(action["id"])["ok"] is True

    result = approvals.answer(
        action["id"], answers={"target": "staging"}, source="web:user")

    assert result["event"] == "reply_rejected"
    record = store.get_pending(action["id"])
    assert record is not None
    assert record["status"] == "rejected"


def test_naive_expiry_and_non_string_answers_fail_closed():
    action = approvals.request_answers(
        title="Pick target",
        description="",
        questions=[{
            "id": "target",
            "text": "Where?",
            "options": [{"value": "1", "label": "One"}],
        }],
        origin="test",
    )
    store.resolve_pending(
        action["id"],
        "pending",
        details={"expires_at": "2099-01-01T00:00:00"},
    )

    result = approvals.answer(
        action["id"], answers={"target": 1}, source="web:user")

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
        store.resolve_pending(
            record["id"], "answered", details={"status": "pending"})


def test_execute_cron_clamps_and_defaults_clock(monkeypatch):
    # A cron payload may carry garbage ("9; rm") or out-of-range values (25, 999);
    # execute_action must default on garbage and clamp, never raise or store a
    # time that can't fire.
    captured = []
    monkeypatch.setattr(cron, "add_job",
                        lambda **kw: (captured.append(kw) or {
                            "id": "1", "name": kw["name"],
                            "hour": kw["hour"], "minute": kw["minute"]}))
    approvals.execute_action("cron", {"name": "j", "hour": "9; rm", "minute": 999})
    assert captured[-1]["hour"] == 9 and captured[-1]["minute"] == 59
    approvals.execute_action("cron", {"name": "j", "hour": 25, "minute": -5})
    assert captured[-1]["hour"] == 23 and captured[-1]["minute"] == 0
