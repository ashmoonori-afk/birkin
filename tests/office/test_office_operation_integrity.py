from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest
from docx import Document

from birkin import approvals, config, store
from birkin.office.artifact_serialization import canonical_json
from birkin.office.job import OfficeJob
from birkin.tools import build_registry
from birkin.tools._types import ToolContext
from tests.office.test_office_coordinator import _sha256
from tests.office.test_office_job import FakeRunner


def _proposal(value: str) -> tuple[str, str]:
    job = OfficeJob(
        job_id=f"job-{value[-1]}",
        format_name="xlsx",
        source={"uri": "source.xlsx", "content_hash": "source-sha"},
        runner=FakeRunner(),
    )
    job.declare_outcome("Set the credential cell")
    job.propose_operations([{"cell": "A1", "value": value}])
    _ = job.build_preview()
    approval = job.request_approval()
    return cast(str, approval["proposal_digest"]), canonical_json(approval)


def test_proposal_digest_binds_unredacted_operation_values() -> None:
    # Given: two exact operations that redact to the same public evidence.
    first = "api_key=AAAA1111"
    second = "api_key=BBBB2222"

    # When: each operation crosses the approval-integrity boundary.
    first_digest, first_evidence = _proposal(first)
    second_digest, second_evidence = _proposal(second)

    # Then: authority differs while caller-visible evidence remains redacted.
    assert first_digest != second_digest
    assert first not in first_evidence
    assert second not in second_evidence
    assert "[redacted]" in first_evidence
    assert "[redacted]" in second_evidence


def _queued_docx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, object], dict[str, object], Path, Path, str]:
    home = tmp_path / "home"
    caller = tmp_path / "caller"
    home.mkdir()
    caller.mkdir()
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    source = home / "source.docx"
    destination = caller / "approved.docx"
    document = Document()
    _ = document.add_paragraph("Original credential placeholder")
    document.save(str(source))
    source_sha256 = _sha256(source)
    result = build_registry(
        ToolContext(cfg={}, client=None, cwd=caller, record_source="user:integrity"),
        include={"documents"},
    ).execute(
        "office_job_request",
        {
            "request": "Update this Word DOCX paragraph",
            "source": {"content_hash": source_sha256, "uri": str(source)},
            "outcome": "Set the credential paragraph",
            "operations": [
                {
                    "locator": {"format": "docx", "index": 1},
                    "value": "api_key=AAAA1111",
                }
            ],
            "destination": str(destination),
        },
    )
    body = cast("dict[str, object]", json.loads(cast(str, result.content)))
    record = store.get_pending(cast(str, body["id"]))
    assert not result.is_error, body
    assert record is not None
    return body, record, source, destination, source_sha256


def test_legacy_redacting_digest_cannot_authorize_substituted_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a queued job whose latest snapshot is changed to a redaction collision.
    body, record, source, destination, source_sha256 = _queued_docx(
        tmp_path, monkeypatch
    )
    payload = cast("dict[str, object]", record["payload"])
    job_id = cast(str, payload["job_id"])
    journal = config.birkin_home() / "office" / "jobs" / f"{job_id}.jsonl"
    records = journal.read_text(encoding="utf-8").splitlines()
    latest = cast("dict[str, object]", json.loads(records[-1]))
    original_operations = cast("list[dict[str, object]]", latest["operations"])
    substituted = [{**original_operations[0], "value": "api_key=BBBB2222"}]
    latest["operations"] = substituted
    records[-1] = json.dumps(latest, ensure_ascii=False, sort_keys=True)
    _ = journal.write_text("\n".join(records) + "\n", encoding="utf-8")
    legacy_proposal = {
        "operations": [{**original_operations[0], "value": "api_key=AAAA1111"}],
        "source_sha256": payload["source_sha256"],
        "outcome": latest["outcome"],
    }
    legacy_digest = hashlib.sha256(
        canonical_json(legacy_proposal).encode("utf-8")
    ).hexdigest()
    record["payload"] = {**payload, "proposal_digest": legacy_digest}
    _ = config.pending_dir().joinpath(f"{body['id']}.json").write_text(
        json.dumps(record), encoding="utf-8"
    )

    # When: the insecure legacy authority is presented for execution.
    result = approvals.approve(cast(str, body["id"]))

    # Then: substitution fails closed before source or destination mutation.
    assert result["ok"] is False
    assert "POLICY_DENIED" in cast(str, result["error"])
    assert _sha256(source) == source_sha256
    assert not destination.exists()
