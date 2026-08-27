"""Natural-language Companion entry: the model proposes, approval activates.

The one door a model gets is ``companion_propose`` → a *candidate* plus a
pending approval. Activation happens only in the approval executor, and the
state files are control-plane-protected so the tool loop cannot go around.
"""

from __future__ import annotations

import types

import pytest

from birkin import approvals, companion, config, store

CHAT = "telegram:777"
AT = "2026-08-01T09:00:00+09:00"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    return tmp_path


def _bound(enabled: bool = True):
    companion.bind_context(CHAT, owner_id="777")
    if enabled:
        companion.set_policy(enabled=True)


def test_propose_queues_and_does_not_activate():
    _bound()
    status = companion.propose_checkin(outcome="ship the draft",
                                       check_in_at=AT, cfg={})
    assert status["auto"] is False
    record = companion.get_commitment(status["commitment_id"])
    assert record["status"] == "candidate"          # nothing scheduled yet
    pending = [r for r in store.list_pending()
               if r.get("category") == "companion"]
    assert len(pending) == 1
    assert pending[0]["payload"]["commitment_id"] == record["id"]


def test_approval_activates_the_commitment():
    _bound()
    status = companion.propose_checkin(outcome="ship the draft",
                                       check_in_at=AT, cfg={})
    resolved = approvals.approve(status["id"], approved_by="human:test", approved_via="test")
    assert resolved.get("ok"), resolved
    record = companion.get_commitment(status["commitment_id"])
    assert record["status"] == "active"
    assert record["check_in_at"] == AT


def test_auto_approve_opt_in_applies_immediately():
    _bound()
    status = companion.propose_checkin(outcome="ship the draft",
                                       check_in_at=AT,
                                       cfg={"auto_approve": ["companion"]})
    assert status["auto"] is True and status["ok"] is True
    assert companion.get_commitment(status["commitment_id"])["status"] == "active"


def test_propose_refuses_when_policy_disabled():
    _bound(enabled=False)
    with pytest.raises(companion.CompanionError, match="disabled"):
        companion.propose_checkin(outcome="x", check_in_at=AT, cfg={})


def test_propose_refuses_without_a_bound_context():
    companion.set_policy(enabled=True)
    with pytest.raises(companion.CompanionError, match="no bound context"):
        companion.propose_checkin(outcome="x", check_in_at=AT, cfg={})


def test_propose_refuses_garbage_time():
    _bound()
    with pytest.raises(companion.CompanionError, match="unparseable"):
        companion.propose_checkin(outcome="x", check_in_at="tomorrowish",
                                  cfg={})


def test_executor_rejects_a_payload_without_commitment_id():
    with pytest.raises(companion.CompanionError):
        approvals.execute_action("companion", {})


def test_registry_gates_the_tool_on_setup():
    from birkin.tools import ToolContext, build_registry
    ctx = ToolContext(cfg={}, client=None, cwd=config.birkin_home())
    assert "companion_propose" not in build_registry(ctx).names()
    _bound()
    assert "companion_propose" in build_registry(ctx).names()


def test_tool_reports_errors_instead_of_raising():
    from birkin.tools import companion_tool
    ctx = types.SimpleNamespace(cfg={})
    result = companion_tool.tools()[0].fn({"outcome": "x", "check_in_at": AT},
                                          ctx)
    assert result.is_error
    assert "disabled" in result.content


def test_file_tools_refuse_the_companion_store():
    from birkin.tools import files
    _bound()
    ctx = types.SimpleNamespace(cwd=config.birkin_home(), cfg={})
    target = config.birkin_home() / "companion" / "state.json"
    before = target.read_text(encoding="utf-8")
    tool = {t.name: t for t in files.tools()}["write_file"]
    result = tool.fn({"path": str(target), "content": "{}"}, ctx)
    assert result.is_error
    assert "protected" in result.content
    assert target.read_text(encoding="utf-8") == before
