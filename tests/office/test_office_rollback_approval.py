from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from birkin import approvals, store
from birkin.office import retention_backup_cleanup
from birkin.office.errors import DocumentError
from birkin.office.rollback_approval import execute_approved_rollback
from birkin.tools import build_registry
from birkin.tools._types import ToolContext
from birkin.workspace.approval_projection import approval_item
from tests.office.test_office_coordinator import _request, queue_office_job


def test_export_rollback_requires_second_human_approval(
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
    assert exported["ok"] is True
    job_receipt = cast(
        dict[str, object],
        json.loads(cast(str, exported["result"])),
    )
    registry = build_registry(
        ToolContext(
            cfg={"auto_approve": ["office_rollback"]},
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
    body = cast(dict[str, object], json.loads(cast(str, proposed.content)))
    assert not proposed.is_error, body
    assert body["auto"] is False
    pending = store.get_pending(cast(str, body["id"]))
    assert destination.is_file()
    assert pending is not None
    assert pending["category"] == "office_rollback"
    projected = approval_item(pending)
    assert projected["sealed"] is True
    assert projected["risk"] == "high"
    rollback_payload = cast(dict[str, object], pending["payload"])

    rolled_back = approvals.approve(
        cast(str, body["id"]),
        approved_by="human:rollback-reviewer",
        approved_via="test:office-rollback",
    )

    assert rolled_back["ok"] is True, rolled_back
    assert not destination.exists()
    completed = store.get_pending(cast(str, body["id"]))
    assert completed is not None
    assert completed["approved_by"] == "human:rollback-reviewer"
    rollback_receipt = cast(
        dict[str, object],
        json.loads(cast(str, rolled_back["result"])),
    )
    assert rollback_receipt["approval_id"] == body["id"]
    assert rollback_receipt["approved_by"] == "human:rollback-reviewer"
    assert rollback_receipt["approved_via"] == "test:office-rollback"

    with pytest.raises(DocumentError, match="not executing"):
        _ = execute_approved_rollback(
            rollback_payload,
            approval_id=cast(str, body["id"]),
        )
    _ = store.resolve_pending(cast(str, body["id"]), "executing")
    recovered = json.loads(
        execute_approved_rollback(
            rollback_payload,
            approval_id=cast(str, body["id"]),
        )
    )
    assert recovered == rollback_receipt
    _ = destination.write_text("post-rollback drift", encoding="utf-8")
    with pytest.raises(DocumentError, match="completed rollback state changed"):
        _ = execute_approved_rollback(
            rollback_payload,
            approval_id=cast(str, body["id"]),
        )


def test_rollback_executor_rejects_direct_invocation(
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
    body = cast(dict[str, object], json.loads(cast(str, proposed.content)))
    pending = store.get_pending(cast(str, body["id"]))
    assert pending is not None

    with pytest.raises(DocumentError, match="authority is required"):
        _ = execute_approved_rollback(
            cast(dict[str, object], pending["payload"]),
            approval_id=None,
        )

    assert destination.exists()


def test_rollback_cleanup_failure_remains_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    office_home = home / "office"
    office_home.mkdir(parents=True)
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "approved.xlsx"
    original = b"original workbook bytes"
    _ = destination.write_bytes(original)
    request, _, _ = _request(office_home, destination)
    request["overwrite_approved"] = True
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    registry = build_registry(
        ToolContext(
            cfg={},
            client=None,
            cwd=caller,
            record_source="user:rollback-requester",
        ),
        include={"documents"},
    )
    queued_export = registry.execute("office_job_request", request)
    export_body = cast(
        dict[str, object],
        json.loads(cast(str, queued_export.content)),
    )
    exported = approvals.approve(
        cast(str, export_body["id"]),
        approved_by="human:export-reviewer",
        approved_via="test:office-export",
    )
    job_receipt = cast(
        dict[str, object],
        json.loads(cast(str, exported["result"])),
    )
    queued_rollback = registry.execute(
        "office_rollback_request",
        {"job_id": cast(str, job_receipt["job_id"])},
    )
    rollback_body = cast(
        dict[str, object],
        json.loads(cast(str, queued_rollback.content)),
    )
    approval_id = cast(str, rollback_body["id"])
    real_move = retention_backup_cleanup.move_no_replace
    failed = False

    def fail_backup_cleanup(
        source: Path,
        destination_path: Path,
    ) -> None:
        nonlocal failed
        if source.suffix == ".bak" and not failed:
            failed = True
            raise OSError("injected backup cleanup failure")
        real_move(source, destination_path)

    monkeypatch.setattr(
        retention_backup_cleanup,
        "move_no_replace",
        fail_backup_cleanup,
    )
    interrupted = approvals.approve(
        approval_id,
        approved_by="human:rollback-reviewer",
        approved_via="test:office-rollback",
    )

    assert interrupted["ok"] is False
    assert "recovery required" in cast(str, interrupted["error"])
    pending = store.get_pending(approval_id)
    assert pending is not None
    assert pending["status"] == "executing"
    assert destination.read_bytes() == original

    monkeypatch.setattr(
        retention_backup_cleanup,
        "move_no_replace",
        real_move,
    )
    recovered = approvals.approve(
        approval_id,
        approved_by="human:rollback-reviewer",
        approved_via="test:office-rollback",
    )
    assert recovered["ok"] is True
    completed = store.get_pending(approval_id)
    assert completed is not None
    assert completed["status"] == "approved"
