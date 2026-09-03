"""A denial without a reason stops the loop; with one, it converges.

hermes ships /deny <reason> so the agent course-corrects. birkin's ported
shellguard queued dangerous commands but a refusal carried nothing back, so
the model either retried a variant blind or gave up.
"""

from __future__ import annotations

from birkin import approvals, store


def _proposed(cfg) -> str:
    status = approvals.propose(
        category="shell", title="shell: rm -rf build",
        description="flagged", payload={"command": "rm -rf build"},
        cfg=cfg, origin="shellguard")
    return status["id"]


def test_reject_persists_the_reason(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    aid = _proposed({"auto_approve": []})
    assert approvals.reject(aid, reason="build/ is checked in here", rejected_by="human:test", rejected_via="test")["ok"]
    rec = store.get_pending(aid)
    assert rec["status"] == "rejected"
    assert rec["deny_reason"] == "build/ is checked in here"


def test_reject_without_a_reason_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    aid = _proposed({"auto_approve": []})
    assert approvals.reject(aid, rejected_by="human:test", rejected_via="test")["ok"]
    assert "deny_reason" not in store.get_pending(aid)


def test_denial_reason_is_looked_up_by_exact_command(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    aid = _proposed({"auto_approve": []})
    approvals.reject(aid, reason="build/ is checked in here", rejected_by="human:test", rejected_via="test")
    assert approvals.denial_reason_for("rm -rf build") == \
        "build/ is checked in here"
    assert approvals.denial_reason_for("rm -rf dist") == ""
    assert approvals.denial_reason_for("") == ""


def test_shellguard_hands_the_prior_reason_back_to_the_model(tmp_path,
                                                             monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    cfg = {"auto_approve": []}
    approvals.reject(_proposed(cfg), reason="build/ is checked in here", rejected_by="human:test", rejected_via="test")

    from birkin import shellguard
    result = shellguard._queue_for_approval("rm -rf build", "destructive", cfg)
    assert "queued for approval" in result.content
    assert "build/ is checked in here" in result.content
    assert "retrying a variant" in result.content


def test_gateway_deny_command_parses_id_and_reason(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    aid = _proposed({"auto_approve": []})
    from birkin.gateway.core import Gateway
    gw = Gateway.__new__(Gateway)

    assert "형식" in gw.deny_command(
        "",
        actor_id="human:telegram:42",
        via="gateway:telegram",
    )
    out = gw.deny_command(
        f"{aid} 그 디렉터리는 커밋돼 있어요",
        actor_id="human:telegram:42",
        via="gateway:telegram",
    )
    assert "거부" in out
    assert store.get_pending(aid)["deny_reason"] == "그 디렉터리는 커밋돼 있어요"
    assert "already resolved" in gw.deny_command(
        f"{aid} 다시",
        actor_id="human:telegram:42",
        via="gateway:telegram",
    )


def test_deny_is_a_privileged_gateway_command():
    from birkin.gateway import core
    from birkin.gateway.turn_support import PRIVILEGED_COMMANDS
    assert "deny" in PRIVILEGED_COMMANDS
    assert core.match_command("/deny abc why not") == ("deny", "abc why not")
