"""Worker approval persistence and failure outcome coverage."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from birkin import (
    approval_execution,
    approvals,
    harness,
    store,
    worker_executor,
    worker_request,
)
from birkin.approval_execution_codec import json_mapping
from birkin.tools import worker_tool
from tests.worker_approval_support import (
    FakeRunResult,
    FakeSubprocess,
    RunResult,
    context,
    mapping,
    pending,
    text,
)


def test_approved_harness_refine_persists_private_digest_bound_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    sentinel = "C001 approved refine semantic sentinel"
    request: worker_request.JsonObject = {
        "worker": "harness",
        "action": "refine",
        "target": sentinel,
        "scope": "local",
    }

    proposed = worker_tool.tools()[0].fn(request, context(tmp_path))
    assert not proposed.is_error
    record = pending()
    payload = mapping(record.get("payload"), "worker payload")
    request_dir = harness.refine_requests_dir("local")
    assert not request_dir.exists()

    approved = mapping(
        approvals.approve(
            text(record, "id"),
            approved_by="human:test",
            approved_via="test",
        ),
        "approval result",
    )

    assert approved["ok"] is True
    result = approved["result"]
    if not isinstance(result, str):
        raise AssertionError("approval result must be text")
    assert "[exit 0]" in result
    artifacts = harness.refine_requests("local")
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact == {
        "schema": 2,
        "id": artifact["id"],
        "target": sentinel,
        "instructions": sentinel,
        "scope": "local",
        "session_id": "default",
        "created_at": artifact["created_at"],
        "status": "recorded",
        "request_digest": payload["digest"],
    }
    assert "approved refine request" not in result.lower()
    assert str(artifact["id"]) in result
    artifact_path = harness.refine_request_path(str(artifact["id"]), "local")
    assert str(artifact_path) in result
    assert artifact_path.is_file()
    assert len(artifact_path.read_bytes()) <= harness.REFINE_REQUEST_MAX_BYTES
    assert artifact["created_at"]
    assert harness.history("local") == []
    assert not harness.state_path("local").exists()
    if os.name != "nt":
        assert stat.S_IMODE(artifact_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(request_dir.stat().st_mode) == 0o700

    canonical = json.dumps(
        request, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert artifact["request_digest"] == hashlib.sha256(canonical).hexdigest()


def test_empty_harness_refine_approval_fails_without_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    proposed = worker_tool.tools()[0].fn(
        {"worker": "harness", "action": "refine", "scope": "local"},
        context(tmp_path),
    )
    assert not proposed.is_error
    record = pending()

    approved = approvals.approve(
        text(record, "id"),
        approved_by="human:test",
        approved_via="test",
    )

    assert approved["ok"] is False
    assert not harness.refine_requests_dir("local").exists()


def test_unique_harness_refine_approvals_each_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    for target in ("first unique refinement", "second unique refinement"):
        proposed = worker_tool.tools()[0].fn(
            {
                "worker": "harness",
                "action": "refine",
                "target": target,
                "scope": "global",
            },
            context(tmp_path),
        )
        assert not proposed.is_error
        pending_records = [
            mapping(item, "pending record")
            for item in store.list_pending()
            if item.get("status") == "pending"
        ]
        assert (
            approvals.approve(
                text(pending_records[0], "id"),
                approved_by="human:test",
                approved_via="test",
            )["ok"]
            is True
        )

    artifacts = harness.refine_requests("global")
    assert [item["target"] for item in artifacts] == [
        "first unique refinement",
        "second unique refinement",
    ]
    assert len({item["id"] for item in artifacts}) == 2


def test_approved_odyssey_executes_real_cli_and_persists_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    proposed = worker_tool.tools()[0].fn(
        {"worker": "odyssey", "goal": "C001 approval fidelity sentinel"},
        context(tmp_path),
    )
    assert not proposed.is_error
    record = pending()

    approved = approvals.approve(
        text(record, "id"),
        approved_by="human:test",
        approved_via="test",
    )

    assert approved["ok"] is True
    path = tmp_path / "boulder" / "c001-approval-fidelity-sentinel.json"
    seeded = json_mapping(path.read_text(encoding="utf-8"))
    assert seeded["goal"] == "C001 approval fidelity sentinel"
    assert seeded["seeded"] is True
    assert seeded["active"] is False
    assert seeded["steps"] == []


@pytest.mark.parametrize("failure", ["nonzero", "timeout"])
def test_worker_execution_failure_marks_approval_error(
    failure: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))

    def fail_run(
        argv: tuple[str, ...],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
        shell: bool,
    ) -> RunResult:
        _ = capture_output, text, check, shell
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, timeout)
        return FakeRunResult(stdout="", stderr="worker failed", returncode=7)

    monkeypatch.setattr(worker_executor, "subprocess", FakeSubprocess(run=fail_run))
    proposed = worker_tool.tools()[0].fn(
        {"worker": "morpheus", "action": "run", "dry_run": True},
        context(tmp_path),
    )
    assert not proposed.is_error
    record = pending()

    approved = approval_execution.approve(text(record, "id"), approvals.execute_action, approved_by="human:test", approved_via="test")

    assert approved["ok"] is False
    assert "action failed" in str(approved["error"])
    resolved = store.get_pending(text(record, "id"))
    assert resolved is not None and resolved["status"] == "error"
    assert resolved["failure_stage"] == "action"
