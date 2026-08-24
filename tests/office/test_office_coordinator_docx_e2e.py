from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from script.qa.office_coordinator_docx_e2e import run


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


def test_real_docx_coordinator_flow_emits_complete_clean_evidence(tmp_path: Path) -> None:
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
