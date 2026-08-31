from __future__ import annotations

from typing import Any

import pytest

from birkin import approvals, store, worker_hooks


def _continuation(worker: str = "odyssey") -> dict[str, Any]:
    return {
        "schema": 1,
        "handler": "worker.resume.v1",
        "worker": worker,
        "context": {"checkpoint": "step-2"},
    }


def test_approved_worker_hook_executes_and_resumes_once(
    tmp_path,
    monkeypatch,
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

    result = approvals.approve(queued["id"], on_event=on_event, approved_by="human:test", approved_via="test")

    assert result["ok"] is True
    assert result["result"] == "shell:step"
    assert result["continuation_result"] == "resumed odyssey at step-2"
    assert calls == ["action", "resume"]
    resolved = store.get_pending(queued["id"])
    assert resolved is not None
    assert resolved["status"] == "approved"


def test_rejected_worker_hook_never_executes_or_resumes(
    tmp_path,
    monkeypatch,
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
    assert approvals.reject(queued["id"], reason="not now", rejected_by="human:test", rejected_via="test") == {"ok": True}
    assert calls == []
    assert approvals.approve(queued["id"], on_event=on_event, approved_by="human:test", approved_via="test")["ok"] is False
    assert calls == []
    resolved = store.get_pending(queued["id"])
    assert resolved is not None
    assert resolved["status"] == "rejected"


def test_repeated_worker_hook_approval_is_at_most_once(
    tmp_path,
    monkeypatch,
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

    first = approvals.approve(queued["id"], on_event=on_event, approved_by="human:test", approved_via="test")
    second = approvals.approve(queued["id"], on_event=on_event, approved_by="human:test", approved_via="test")

    assert first["ok"] is True
    assert second["ok"] is False
    assert calls == ["action", "resume"]


def test_worker_hook_preserves_worker_authority_boundaries(
    tmp_path,
    monkeypatch,
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
        "daedalus",
    )
    assert contract["no_model"] == ("mnemosyne", "daedalus")
    assert contract["reserved"] == ("osiris",)
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
        assert approvals.reject(queued["id"], rejected_by="human:test", rejected_via="test") == {"ok": True}

    with pytest.raises(worker_hooks.WorkerHookError, match="unknown worker"):
        approvals.propose(
            category="shell",
            title="unknown worker",
            description="unknown authorities must not enter the queue",
            payload={"command": "step"},
            cfg={"auto_approve": []},
            origin="unknown",
            continuation=_continuation("unknown"),
        )


def test_reserved_worker_cannot_validate_queue_or_dispatch(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    continuation = _continuation("osiris")
    events: list[dict[str, Any]] = []

    with pytest.raises(worker_hooks.WorkerHookError, match="unknown worker: osiris"):
        worker_hooks.validate(continuation)
    with pytest.raises(worker_hooks.WorkerHookError, match="unknown worker: osiris"):
        approvals.propose(
            category="shell",
            title="reserved worker",
            description="reserved authorities must not enter the queue",
            payload={"command": "step"},
            cfg={"auto_approve": []},
            origin="osiris",
            continuation=continuation,
        )
    assert store.list_pending() == []
    with pytest.raises(worker_hooks.WorkerHookError, match="unknown worker: osiris"):
        worker_hooks.dispatch(continuation, on_event=events.append)
    assert events == []


def test_every_accepted_worker_resolves_to_an_implementation() -> None:
    """Every name accepted at the continuation boundary must be reachable."""
    import importlib

    missing = []
    for worker in worker_hooks.WORKERS:
        try:
            importlib.import_module(f"birkin.{worker}")
        except ImportError:
            missing.append(worker)
    assert missing == [], f"accepted but unimplemented workers: {missing}"


def test_reserved_workers_own_no_persistence_they_cannot_write() -> None:
    """A reserved (unimplemented) worker may still delegate persistence.

    ``PERSISTENCE_OWNER`` maps a worker to the worker that owns its durable
    state. For a reserved name the owner must be a real, implemented worker,
    otherwise the mapping points at nothing on both sides.
    """
    import importlib

    for worker, owner in worker_hooks.PERSISTENCE_OWNER.items():
        assert worker in (*worker_hooks.WORKERS, *worker_hooks.RESERVED_WORKERS), (
            f"{worker} is neither an accepted nor reserved worker"
        )
        assert owner in worker_hooks.WORKERS, f"{owner} is not an accepted worker"
        assert owner not in worker_hooks.RESERVED_WORKERS, (
            f"{worker} persistence is owned by reserved worker {owner}"
        )
        importlib.import_module(f"birkin.{owner}")
