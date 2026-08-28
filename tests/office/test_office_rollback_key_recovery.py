from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from birkin import approvals, store
from birkin.office import export_policy
from birkin.tools import build_registry
from birkin.tools._types import ToolContext
from tests.office.test_office_coordinator import queue_office_job


def test_missing_receipt_key_preserves_rollback_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_approval, _, _, destination, _ = queue_office_job(
        tmp_path,
        monkeypatch,
    )
    exported = approvals.approve(
        cast(str, export_approval["id"]),
        approved_by="human:export-reviewer",
        approved_via="test:office-export",
    )
    job_receipt = cast(
        dict[str, object],
        json.loads(cast(str, exported["result"])),
    )
    registry = build_registry(
        ToolContext(
            cfg={},
            client=None,
            cwd=destination.parent,
            record_source="user:rollback-requester",
        ),
        include={"documents"},
    )
    proposed = registry.execute(
        "office_rollback_request",
        {"job_id": cast(str, job_receipt["job_id"])},
    )
    body = cast(
        dict[str, object],
        json.loads(cast(str, proposed.content)),
    )
    approval_id = cast(str, body["id"])
    key = tmp_path / "home" / "office" / "receipt_hmac_key"
    key_bytes = key.read_bytes()
    key.unlink()

    interrupted = approvals.approve(
        approval_id,
        approved_by="human:rollback-reviewer",
        approved_via="test:office-rollback",
    )

    assert interrupted["ok"] is False
    assert not key.exists()
    pending = store.get_pending(approval_id)
    assert pending is not None
    assert pending["status"] == "executing"
    assert destination.exists()

    _ = key.write_bytes(key_bytes)
    recovered = approvals.approve(
        approval_id,
        approved_by="human:rollback-reviewer",
        approved_via="test:office-rollback",
    )
    assert recovered["ok"] is True
    assert not destination.exists()


def test_rollback_sync_failure_preserves_execution_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_approval, _, _, destination, _ = queue_office_job(
        tmp_path,
        monkeypatch,
    )
    exported = approvals.approve(
        cast(str, export_approval["id"]),
        approved_by="human:export-reviewer",
        approved_via="test:office-export",
    )
    job_receipt = cast(
        dict[str, object],
        json.loads(cast(str, exported["result"])),
    )
    registry = build_registry(
        ToolContext(
            cfg={},
            client=None,
            cwd=destination.parent,
            record_source="user:rollback-requester",
        ),
        include={"documents"},
    )
    proposed = registry.execute(
        "office_rollback_request",
        {"job_id": cast(str, job_receipt["job_id"])},
    )
    body = cast(
        dict[str, object],
        json.loads(cast(str, proposed.content)),
    )
    approval_id = cast(str, body["id"])
    real_sync = export_policy.sync_directory
    failed = False

    def fail_once(path: Path, identity: tuple[int, int]) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("injected rollback directory sync failure")
        real_sync(path, identity)

    monkeypatch.setattr(export_policy, "sync_directory", fail_once)
    interrupted = approvals.approve(
        approval_id,
        approved_by="human:rollback-reviewer",
        approved_via="test:office-rollback",
    )

    assert interrupted["ok"] is False
    pending = store.get_pending(approval_id)
    assert pending is not None
    assert pending["status"] == "executing"
    assert not destination.exists()

    recovered = approvals.approve(
        approval_id,
        approved_by="human:rollback-reviewer",
        approved_via="test:office-rollback",
    )
    assert recovered["ok"] is True
    completed = store.get_pending(approval_id)
    assert completed is not None
    assert completed["status"] == "approved"
