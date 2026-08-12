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


def test_execute_action_unknown_category_raises():
    with pytest.raises(ValueError, match="unknown approval category"):
        approvals.execute_action("bogus", {})


def test_execute_claimed_unknown_category_marks_error():
    rec = store.add_pending(
        category="bogus",
        title="Unknown",
        description="",
        payload={},
    )
    aid = rec["id"]
    assert approvals.claim(aid)["ok"] is True

    result = approvals.execute_claimed(aid)

    assert result["ok"] is False
    assert "unknown approval category" in result["error"]
    assert store.get_pending(aid)["status"] == "error"
