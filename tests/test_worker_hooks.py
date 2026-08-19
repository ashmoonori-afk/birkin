from __future__ import annotations

from typing import Any

from birkin import approvals, store


def _continuation(worker: str = "odyssey") -> dict[str, Any]:
    return {
        "schema": 1,
        "handler": "worker.resume.v1",
        "worker": worker,
        "context": {"checkpoint": "step-2"},
    }


def test_approved_worker_hook_executes_and_resumes_once(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    calls: list[str] = []

    def execute_action(
        category: str,
        payload: dict[str, Any],
        cfg: dict[str, Any] | None = None,
        on_event: Any = None,
    ) -> str:
        calls.append("action")
        return f"{category}:{payload['command']}"

    def on_event(event: dict[str, Any]) -> None:
        assert event["type"] == "worker_resume"
        assert event["worker"] == "odyssey"
        calls.append("resume")

    monkeypatch.setattr(approvals, "execute_action", execute_action)
    queued = approvals.propose(
        category="shell",
        title="approved worker step",
        description="run one action, then resume its worker",
        payload={"command": "step"},
        cfg={"auto_approve": []},
        origin="odyssey",
        continuation=_continuation(),
    )

    assert queued["auto"] is False
    assert calls == []
    pending = store.get_pending(queued["id"])
    assert pending is not None
    assert pending["status"] == "pending"
    assert pending["continuation"] == _continuation()

    result = approvals.approve(queued["id"], on_event=on_event)

    assert result["ok"] is True
    assert result["result"] == "shell:step"
    assert result["continuation_result"] == "resumed odyssey at step-2"
    assert calls == ["action", "resume"]
    resolved = store.get_pending(queued["id"])
    assert resolved is not None
    assert resolved["status"] == "approved"


def test_rejected_worker_hook_never_executes_or_resumes(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    calls: list[str] = []

    def execute_action(*args: Any, **kwargs: Any) -> str:
        calls.append("action")
        return "unexpected"

    def on_event(event: dict[str, Any]) -> None:
        calls.append("resume")

    monkeypatch.setattr(approvals, "execute_action", execute_action)
    queued = approvals.propose(
        category="shell",
        title="rejected worker step",
        description="rejection must keep both phases blocked",
        payload={"command": "step"},
        cfg={"auto_approve": []},
        origin="odyssey",
        continuation=_continuation(),
    )

    assert calls == []
    assert approvals.reject(queued["id"], reason="not now") == {"ok": True}
    assert calls == []
    assert approvals.approve(queued["id"], on_event=on_event)["ok"] is False
    assert calls == []
    resolved = store.get_pending(queued["id"])
    assert resolved is not None
    assert resolved["status"] == "rejected"


def test_repeated_worker_hook_approval_is_at_most_once(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    calls: list[str] = []

    def execute_action(*args: Any, **kwargs: Any) -> str:
        calls.append("action")
        return "ran"

    def on_event(event: dict[str, Any]) -> None:
        calls.append("resume")

    monkeypatch.setattr(approvals, "execute_action", execute_action)
    queued = approvals.propose(
        category="shell",
        title="single worker step",
        description="duplicate approval must not duplicate either phase",
        payload={"command": "step"},
        cfg={"auto_approve": []},
        origin="odyssey",
        continuation=_continuation(),
    )

    first = approvals.approve(queued["id"], on_event=on_event)
    second = approvals.approve(queued["id"], on_event=on_event)

    assert first["ok"] is True
    assert second["ok"] is False
    assert calls == ["action", "resume"]


def test_worker_hook_preserves_worker_authority_boundaries(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    contract = approvals.worker_hook_contract()

    assert contract["workers"] == (
        "moirai",
        "mnemosyne",
        "neurosis",
        "morpheus",
        "boulder",
        "harness",
        "odyssey",
        "osiris",
        "daedalus",
    )
    assert contract["no_model"] == ("mnemosyne", "daedalus")
    assert contract["persistence_owner"] == {"osiris": "boulder"}

    for worker in contract["workers"]:
        queued = approvals.propose(
            category="shell",
            title=f"{worker} worker step",
            description="all workers use the same approval hook contract",
            payload={"command": "step"},
            cfg={"auto_approve": []},
            origin=worker,
            continuation=_continuation(worker),
        )
        pending = store.get_pending(queued["id"])
        assert pending is not None
        assert pending["continuation"]["worker"] == worker
        assert approvals.reject(queued["id"]) == {"ok": True}

    try:
        approvals.propose(
            category="shell",
            title="unknown worker",
            description="unknown authorities must not enter the queue",
            payload={"command": "step"},
            cfg={"auto_approve": []},
            origin="unknown",
            continuation=_continuation("unknown"),
        )
    except ValueError as exc:
        assert "unknown worker" in str(exc)
    else:
        raise AssertionError("unknown worker continuation was accepted")
