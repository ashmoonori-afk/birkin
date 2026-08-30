from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import cast

import pytest

from birkin import approvals
from birkin.office.job_types import OfficeJobState
from birkin.office.progress import office_progress_payload
from birkin.tools import build_registry
from birkin.tools._types import ToolContext


def _terminal_request(
    office_home: Path,
    destination: Path,
) -> dict[str, object]:
    source = office_home / "source.xlsx"
    parts = {
        "[Content_Types].xml": b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>',
        "xl/workbook.xml": b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Revenue" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><v>7</v></c></row></sheetData></worksheet>',
    }
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    return {
        "request": "Update cell A1 in this Excel workbook",
        "source": {
            "artifact_id": source_sha256,
            "content_hash": source_sha256,
            "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "uri": str(source),
            "sensitivity": "internal",
            "acl_fingerprint": "local-contract",
        },
        "outcome": "Set Revenue A1 to 9",
        "operations": [{"cell": "A1", "value": 9}],
        "destination": str(destination),
    }


@pytest.mark.parametrize(
    ("state", "phase", "status", "ui_state"),
    [
        (OfficeJobState.input_captured, "inspection", "working", "pending"),
        (OfficeJobState.operations_proposed, "comparison", "working", "pending"),
        (OfficeJobState.approved, "draft", "working", "pending"),
        (OfficeJobState.validated, "validation", "working", "pending"),
        (OfficeJobState.exported, "export", "succeeded", "succeeded"),
    ],
)
def test_office_progress_payload_maps_user_visible_stages(
    state: OfficeJobState,
    phase: str,
    status: str,
    ui_state: str,
) -> None:
    payload = office_progress_payload("job-progress", state)

    assert payload is not None
    assert payload["progress_id"] == "office:job-progress"
    assert payload["runtime_event"] == f"office.{phase}"
    assert payload["office_phase"] == phase
    assert payload["job_id"] == "job-progress"
    assert payload["status"] == status
    assert payload["ui_state"] == ui_state
    assert isinstance(payload["summary"], str)
    assert payload["summary"]


@pytest.mark.parametrize(
    "state",
    [
        OfficeJobState.outcome_declared,
        OfficeJobState.preview_ready,
        OfficeJobState.approval_requested,
        OfficeJobState.executed,
        OfficeJobState.rejected,
        OfficeJobState.failed,
    ],
)
def test_office_progress_payload_omits_duplicate_internal_states(
    state: OfficeJobState,
) -> None:
    assert office_progress_payload("job-progress", state) is None


def test_terminal_office_tool_emits_all_five_progress_phases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    office_home = home / "office"
    caller = tmp_path / "caller"
    office_home.mkdir(parents=True)
    caller.mkdir()
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    request = _terminal_request(office_home, caller / "approved.xlsx")
    events: list[tuple[str, dict[str, object]]] = []

    def emit(event: str, payload: dict[str, object]) -> None:
        events.append((event, payload))

    registry = build_registry(
        ToolContext(
            cfg={},
            client=None,
            cwd=caller,
            emit=emit,
            record_source="user:terminal-progress",
        ),
        include={"documents"},
    )

    proposed = registry.execute("office_job_request", request)
    body = cast("dict[str, object]", json.loads(cast(str, proposed.content)))
    approved = approvals.approve(
        cast(str, body["id"]),
        on_event=emit,
        approved_by="human:terminal-progress",
        approved_via="terminal:review",
    )

    assert not proposed.is_error, body
    assert approved["ok"] is True, approved
    progress = [
        payload for event, payload in events if event == "office_progress"
    ]
    assert [payload["office_phase"] for payload in progress] == [
        "inspection",
        "comparison",
        "draft",
        "validation",
        "export",
    ]
    assert len({payload["progress_id"] for payload in progress}) == 1
