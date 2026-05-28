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


def test_propose_consequential_is_queued():
    cfg = {"auto_approve": ["memory", "skills"]}
    res = approvals.propose(category="cron", title="Digest", description="d",
                            payload={"name": "digest", "hour": 9, "minute": 0,
                                     "type": "prompt", "value": "go"}, cfg=cfg)
    assert res["auto"] is False
    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0]["title"] == "Digest"


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
