from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import cast

import pytest
from birkin import store
from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.workspace.contracts import (
    ClientContext,
    ProtocolError,
    WorkspaceCommand,
)
from birkin.workspace.approval_projection import approval_item
from birkin.workspace.records import CommandReceipt
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter
from birkin.workspace.service import WorkspaceService


FIXTURES = (
    Path("windows/BirkinNativeApp/tests/Birkin.Native.App.Tests/Fixtures/Office")
)


def _single_cell_xlsx(path: Path, *, value: int = 7) -> Path:
    parts = {
        "[Content_Types].xml": b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>',
        "xl/workbook.xml": b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Revenue" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData><row r="1"><c r="A1"><v>{value}</v></c></row></sheetData>'
            "</worksheet>"
        ).encode(),
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)
    return path


def _service(
    tmp_path: Path,
) -> tuple[WorkspaceService, RuntimeWorkspaceAdapter]:
    service = WorkspaceService(
        root=tmp_path / "journal", session_id="office-journey", handlers={}
    )
    adapter = RuntimeWorkspaceAdapter(
        "office-journey", service.emit, workspace_root=tmp_path / "workspace"
    )
    service.set_handlers(adapter.handlers())
    return service, adapter


def _submit(
    service: WorkspaceService,
    command_id: str,
    command_type: str,
    payload: dict[str, object],
) -> tuple[CommandReceipt, dict[str, object]]:
    command = WorkspaceCommand(
        protocol_version=1,
        command_id=command_id,
        expected_cursor=service.snapshot().cursor,
        type=command_type,
        payload=payload,
        client_context=ClientContext(surface="windows", view_id="office"),
    )
    receipt = service.submit(command, actor_id="windows:office")
    result = receipt.transient_result
    assert receipt.state == "completed"
    assert isinstance(result, dict)
    return receipt, result


def _artifact(result: dict[str, object]) -> dict[str, object]:
    artifact = result.get("artifact")
    assert isinstance(artifact, dict)
    return cast(dict[str, object], artifact)


def _import(
    service: WorkspaceService,
    command_id: str,
    source: Path,
) -> dict[str, object]:
    _receipt, imported = _submit(
        service,
        command_id,
        "file.import",
        {"source_path": str(source.resolve())},
    )
    return _artifact(imported)


def test_file_import_registers_office_artifacts_by_copy_without_client_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    service, adapter = _service(tmp_path)
    assert adapter.surface_authority.office.service.home == (
        tmp_path / "home" / "office"
    ).resolve()
    source = tmp_path / "outside" / "baseline.xlsx"
    source.parent.mkdir()
    _ = source.write_bytes((FIXTURES / "baseline.xlsx").read_bytes())

    _receipt, imported = _submit(
        service, "import-baseline", "file.import", {"source_path": str(source)}
    )
    artifact = _artifact(imported)
    registered = Path(cast(str, artifact["uri"]))
    _ = source.write_bytes(b"changed after authoritative copy")

    assert set(imported) == {"reference", "artifact", "receipt"}
    assert registered.is_relative_to(adapter.surface_authority.office.service.home)
    assert registered.read_bytes() != source.read_bytes()
    assert hashlib.sha256(registered.read_bytes()).hexdigest() == artifact["content_hash"]
    assert str(source) not in str(imported)

    with pytest.raises(ValueError, match="canonical source_path"):
        _ = _submit(
            service,
            "import-traversal",
            "file.import",
            {"source_path": str(source), "destination": "../escape.xlsx"},
        )
    assert not (tmp_path / "escape.xlsx").exists()


def test_native_office_rejects_hashed_source_outside_dedicated_jail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    birkin_home = tmp_path / "home"
    monkeypatch.setenv("BIRKIN_HOME", str(birkin_home))
    _service_instance, adapter = _service(tmp_path)
    outside = _single_cell_xlsx(birkin_home / "vault.xlsx")
    digest = hashlib.sha256(outside.read_bytes()).hexdigest()

    with pytest.raises(DocumentError) as caught:
        _ = adapter.surface_authority.office.service.inspect_document(
            {"content_hash": digest, "uri": str(outside)}
        )

    assert caught.value.code in {
        DocumentErrorCode.PERMISSION_DENIED,
        DocumentErrorCode.SOURCE_CHANGED,
    }


def test_compare_is_read_only_and_office_draft_is_not_a_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    service, adapter = _service(tmp_path)
    left = _import(service, "import-left", FIXTURES / "baseline.xlsx")
    right = _import(service, "import-right", FIXTURES / "candidate.xlsx")
    drafts = adapter.surface_authority.office.service.home / "artifacts" / "drafts"
    before = list(drafts.iterdir())

    receipt, compared = _submit(
        service,
        "compare-spreadsheets",
        "office.compare",
        {
            "left_artifact_id": left["artifact_id"],
            "right_artifact_id": right["artifact_id"],
        },
    )

    diff = cast(dict[str, object], compared["diff"])
    assert isinstance(diff["diff_id"], str)
    assert receipt.result_event_cursor is not None
    assert list(drafts.iterdir()) == before
    assert not (adapter.surface_authority.office.service.home / "artifacts" / "staging").exists()
    assert "office.draft" not in adapter.handlers()
    with pytest.raises(ProtocolError, match="unsupported command type"):
        _ = WorkspaceCommand.parse(
            {
                "protocol_version": 1,
                "command_id": "legacy-draft",
                "expected_cursor": service.snapshot().cursor,
                "type": "office.draft",
                "payload": {},
                "client_context": {"surface": "windows", "view_id": "office"},
            }
        )

    diff_event = next(event for event in service.events() if event.type == "office.diff_ready")
    assert diff_event.command_id == "compare-spreadsheets"
    projected = adapter.surface_authority.office.snapshot()
    assert cast(list[object], projected["diffs"])[-1] == diff


def test_native_office_job_request_creation_queues_then_exports_real_docx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    service, adapter = _service(tmp_path)
    destination = tmp_path / "workspace" / "created-report.docx"
    drafts = adapter.surface_authority.office.service.home / "artifacts" / "drafts"

    _, proposed = _submit(
        service,
        "direct-create",
        "office.job_request",
        {
            "request": "새 보고서를 DOCX로 만들어 주세요.",
            "format": "docx",
            "content": {"paragraphs": ["새 보고서", "승인된 본문"]},
            "outcome": "새 보고서 작성",
            "destination": str(destination),
            "overwrite_approved": False,
        },
    )

    approval_id = cast(str, proposed["id"])
    pending = store.get_pending(approval_id)
    assert proposed["category"] == "office_create"
    assert pending is not None
    assert approval_item(pending)["sealed"] is True
    requested = next(
        event
        for event in service.events()
        if event.type == "approval.requested"
        and event.command_id == "direct-create"
    )
    assert requested.payload["approval_id"] == approval_id
    assert requested.payload["category"] == "office_create"
    assert requested.payload["job_id"] == cast(
        "dict[str, object]",
        proposed["approval"],
    )["job_id"]
    assert requested.payload["sealed"] is True
    assert not destination.exists()
    assert not list(drafts.iterdir())

    _, answered = _submit(
        service,
        "approve-create",
        "approval.answer",
        {
            "approval_id": approval_id,
            "decision": "approve",
            "reason": "Create the requested report.",
        },
    )

    receipt = cast(
        "dict[str, object]",
        json.loads(cast(str, answered["receipt"])),
    )
    exported = cast("dict[str, object]", receipt["export"])
    assert answered["outcome"] == "approved"
    assert receipt["state"] == "exported"
    assert destination.is_file()
    assert exported["output_sha256"] == hashlib.sha256(
        destination.read_bytes()
    ).hexdigest()
    with zipfile.ZipFile(destination) as package:
        document_xml = package.read("word/document.xml").decode("utf-8")
    assert "새 보고서" in document_xml
    assert "승인된 본문" in document_xml


def test_native_create_rejects_unbound_payload_fields_without_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a creation command carrying an unreviewed extra field.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    service, adapter = _service(tmp_path)
    destination = tmp_path / "workspace" / "unbound.docx"
    drafts = adapter.surface_authority.office.service.home / "artifacts" / "drafts"

    # When: the strict native boundary parses the command.
    with pytest.raises(DocumentError) as caught:
        _ = _submit(
            service,
            "unbound-create",
            "office.create",
            {
                "format": "docx",
                "content": {
                    "paragraphs": ["검토된 본문"],
                    "unreviewed": "hidden content",
                },
                "output_name": "unbound.docx",
            },
        )

    # Then: the extra field fails closed before approval or file creation.
    assert caught.value.code is DocumentErrorCode.INVALID_INPUT
    assert not destination.exists()
    assert not list(drafts.iterdir())


def test_native_office_job_request_queues_current_canonical_proposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    service, adapter = _service(tmp_path)
    source_path = _single_cell_xlsx(tmp_path / "source.xlsx")
    source = _import(service, "import-job-source", source_path)
    duplicate = _single_cell_xlsx(tmp_path / "same-content-different-name.xlsx")
    _ = _import(service, "import-job-duplicate", duplicate)
    for index in range(8):
        filler = _single_cell_xlsx(
            tmp_path / f"filler-{index}.xlsx",
            value=100 + index,
        )
        _ = _import(service, f"import-filler-{index}", filler)
    destination = tmp_path / "workspace" / "approved.xlsx"

    receipt, proposed = _submit(
        service,
        "request-office-job",
        "office.job_request",
        {
            "request": "Update cell A1 in this Excel workbook",
            "source": {**source, "source_filename": "forged-name.xlsx"},
            "outcome": "Set Comparison A1 to 9",
            "operations": [{"cell": "A1", "value": 9}],
            "destination": str(destination),
        },
    )

    approval_id = cast(str, proposed["id"])
    approval = cast(dict[str, object], proposed["approval"])
    pending = store.get_pending(approval_id)
    assert receipt.result_event_cursor is not None
    assert proposed["category"] == "office_job"
    assert pending is not None and pending["category"] == "office_job"
    assert pending["payload"] == approval
    assert approval["source_sha256"] == source["content_hash"]
    assert approval["destination"] == str(destination)
    assert approval["allowlist_root"] == str((tmp_path / "workspace").resolve())
    assert approval["proposer"] == "native:office-journey"
    assert approval["source_filename"] == "source.xlsx"
    assert approval["source_filename"] != "forged-name.xlsx"
    assert isinstance(approval["job_id"], str)
    assert isinstance(approval["proposal_digest"], str)
    assert isinstance(approval["authority_digest"], str)
    assert not destination.exists()
    assert not (adapter.surface_authority.office.service.home / "artifacts" / "staging").exists()

    requested = next(event for event in service.events() if event.type == "approval.requested")
    assert requested.command_id == "request-office-job"
    assert requested.payload["approval_id"] == approval_id
    assert requested.payload["category"] == "office_job"
    assert requested.payload["job_id"] == approval["job_id"]
    assert requested.payload["proposal_digest"] == approval["proposal_digest"]
    assert requested.payload["authority_digest"] == approval["authority_digest"]
    assert requested.payload["destination"] == str(destination)
    assert requested.payload["overwrite_approved"] is False
    assert requested.payload["source_filename"] == "source.xlsx"
    assert requested.payload["risk"] == "high"
    assert requested.payload["sealed"] is True
    assert requested.payload["requester"] == "native:office-journey"
    assert requested.payload["rejection_result"] == (
        "Rejecting leaves the source unchanged and writes no output."
    )
    description = cast(str, requested.payload["description"])
    assert "A1" in description
    assert "7" in description
    assert "9" in description
    approval_panel = next(
        panel for panel in service.snapshot().panels if panel.key == "approvals"
    )
    snapshot_item = next(
        item for item in approval_panel.items if item["id"] == approval_id
    )
    assert snapshot_item["risk"] == requested.payload["risk"]
    assert snapshot_item["sealed"] == requested.payload["sealed"]
    assert snapshot_item["destination"] == requested.payload["destination"]
    assert snapshot_item["overwrite_approved"] is False
    assert snapshot_item["source_filename"] == requested.payload["source_filename"]
    assert snapshot_item["authority_digest"] == requested.payload["authority_digest"]
    assert snapshot_item["requester"] == requested.payload["requester"]
    assert snapshot_item["rejection_result"] == requested.payload["rejection_result"]

    imported_path = Path(cast(str, source["uri"]))
    source_before = imported_path.read_bytes()
    _answer_receipt, answered = _submit(
        service,
        "approve-office-job",
        "approval.answer",
        {"approval_id": approval_id, "decision": "approve"},
    )
    resolved = store.get_pending(approval_id)
    assert answered["outcome"] == "approved"
    assert isinstance(answered["receipt"], str)
    assert destination.is_file()
    assert imported_path.read_bytes() == source_before
    assert resolved is not None and resolved["status"] == "approved"
    answered_event = next(
        event for event in service.events() if event.type == "approval.answered"
    )
    assert answered_event.command_id == "approve-office-job"
    assert answered_event.payload["approval_id"] == approval_id
    assert answered_event.payload["receipt"] == answered["receipt"]


def test_native_output_exists_projects_one_click_overwrite_follow_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    service, _ = _service(tmp_path)
    destination = tmp_path / "workspace" / "existing-report.docx"
    existing = b"existing caller file"
    destination.write_bytes(existing)
    _, proposed = _submit(
        service,
        "request-existing-create",
        "office.job_request",
        {
            "request": "기존 경로에 새 DOCX 보고서를 만들어 주세요.",
            "format": "docx",
            "content": {"paragraphs": ["덮어쓴 보고서"]},
            "outcome": "새 보고서 작성",
            "destination": str(destination),
            "overwrite_approved": False,
        },
    )

    _, first = _submit(
        service,
        "approve-without-overwrite",
        "approval.answer",
        {
            "approval_id": proposed["id"],
            "decision": "approve",
        },
    )

    assert first["outcome"] == "follow_up_required"
    assert first["question"] == "기존 파일을 덮어쓸까요?"
    follow_up_id = cast(str, first["follow_up_approval_id"])
    assert destination.read_bytes() == existing
    follow_up = store.get_pending(follow_up_id)
    assert follow_up is not None
    projected = approval_item(follow_up)
    assert projected["summary"] == "기존 파일을 덮어쓸까요?"
    assert projected["overwrite_approved"] is True
    assert projected["overwrite_retry"] is True
    assert projected["retry_of_approval_id"] == proposed["id"]
    requested = next(
        event
        for event in service.events()
        if event.type == "approval.requested"
        and event.command_id == "approve-without-overwrite"
    )
    assert requested.payload["approval_id"] == follow_up_id
    assert requested.payload["summary"] == "기존 파일을 덮어쓸까요?"

    _, second = _submit(
        service,
        "approve-overwrite",
        "approval.answer",
        {
            "approval_id": follow_up_id,
            "decision": "approve",
        },
    )

    assert second["outcome"] == "approved"
    with zipfile.ZipFile(destination) as package:
        document_xml = package.read("word/document.xml").decode("utf-8")
    assert "덮어쓴 보고서" in document_xml
