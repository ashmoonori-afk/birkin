from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from birkin import approvals, store
from docx import Document
from script.qa.office_coordinator_docx_e2e import (
    AFTER,
    _flow,
    _propose,
    _request,
    run,
)


EVIDENCE_FILES = {
    "source-before.sha256",
    "source-after.sha256",
    "destination-timeline.json",
    "approval-record.json",
    "policy-denied.json",
    "receipt.json",
    "journal.jsonl",
    "action-log.txt",
    "cleanup-receipt.json",
}


def test_docx_coordinator_accepts_canonical_equivalent_runtime_paths(
    tmp_path: Path,
) -> None:
    # Given: the driver receives a lexical temp path with a canonical alias.
    runtime = tmp_path / "unused" / ".." / "runtime"
    flow = _flow(runtime, "canonical")

    # When: the real registry prepares the DOCX approval.
    body = _propose(flow, _request(flow))

    # Then: import and export bind to the same canonical filesystem identities.
    approval = cast("dict[str, object]", body["approval"])
    assert flow.home == flow.home.resolve(strict=True)
    assert flow.caller == flow.caller.resolve(strict=True)
    assert approval["destination"] == str(flow.destination)


def test_output_exists_queues_one_click_mutation_overwrite_approval(
    tmp_path: Path,
) -> None:
    flow = _flow(tmp_path, "overwrite-retry")
    body = _propose(flow, _request(flow, overwrite=False))
    original = store.get_pending(cast(str, body["id"]))
    assert original is not None

    first = approvals.approve(
        cast(str, body["id"]),
        approved_by="human:first-reviewer",
        approved_via="test:first-approval",
    )

    assert first["ok"] is False
    assert first["error"] == "기존 파일을 덮어쓸까요?"
    follow_up_id = cast(str, first["follow_up_approval_id"])
    assert flow.destination.read_bytes() == flow.destination_before
    follow_up = store.get_pending(follow_up_id)
    assert follow_up is not None
    assert follow_up["title"] == "기존 파일을 덮어쓸까요?"
    assert follow_up["retry_of_approval_id"] == body["id"]
    assert follow_up["overwrite_retry"] is True
    original_payload = cast("dict[str, object]", original["payload"])
    payload = cast("dict[str, object]", follow_up["payload"])
    assert payload["overwrite_approved"] is True
    assert payload["proposal_digest"] == original_payload["proposal_digest"]
    assert payload["job_id"] != original_payload["job_id"]

    second = approvals.approve(
        follow_up_id,
        approved_by="human:overwrite-reviewer",
        approved_via="test:overwrite-approval",
    )

    assert second["ok"] is True
    assert [
        paragraph.text for paragraph in Document(str(flow.destination)).paragraphs
    ] == [AFTER]


def test_real_docx_coordinator_flow_emits_complete_clean_evidence(
    tmp_path: Path,
) -> None:
    # Given: an isolated evidence destination.
    evidence = tmp_path / "evidence"

    # When: the real registry, approval, export, and rollback driver runs.
    cleanup = run(evidence)

    # Then: every machine-consumed proof exists and all byte/residue invariants hold.
    assert {path.name for path in evidence.iterdir()} == EVIDENCE_FILES
    assert (evidence / "source-before.sha256").read_bytes() == (
        evidence / "source-after.sha256"
    ).read_bytes()
    timeline = cast(
        "dict[str, object]",
        json.loads((evidence / "destination-timeline.json").read_text("utf-8")),
    )
    assert timeline["before_sha256"] == timeline["rollback_sha256"]
    receipt = cast(
        "dict[str, object]",
        json.loads((evidence / "receipt.json").read_text("utf-8")),
    )
    exported = cast("dict[str, object]", receipt["export"])
    assert {
        "source_sha256",
        "output_sha256",
        "operations",
        "actor",
        "proposal_digest",
    } <= set(exported)
    denials = cast(
        "dict[str, dict[str, object]]",
        json.loads((evidence / "policy-denied.json").read_text("utf-8")),
    )
    assert {name: item["code"] for name, item in denials.items()} == {
        "digest_drift": "POLICY_DENIED",
        "outside_root": "PERMISSION_DENIED",
        "overwrite": "OUTPUT_EXISTS",
        "preapproval": "POLICY_DENIED",
    }
    assert cleanup["runtime_removed"] is True
    assert cleanup["drafts_remaining"] == cleanup["backups_remaining"] == []
    assert cleanup["temporary_files_remaining"] == cleanup["jobs_remaining"] == []
    assert cleanup["processes_remaining"] == []
