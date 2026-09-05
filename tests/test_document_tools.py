from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import cast

import pytest

from birkin.tools import build_registry
from birkin.tools._types import Config, ToolContext

def _single_cell_xlsx(path: Path) -> Path:
    parts = {
        "[Content_Types].xml": b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>',
        "xl/workbook.xml": b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Revenue" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><v>7</v></c></row></sheetData></worksheet>',
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)
    return path


NAMES = {
    "list_document_adapters",
    "inspect_document",
    "extract_document",
    "analyze_workbook",
    "review_meeting_actions",
    "list_work_items",
    "work_item_request",
    "search_office_sources",
    "compare_documents",
    "render_artifact",
    "validate_artifact",
    "office_job_request",
    "office_rollback_request",
}
REMOVED_MUTATIONS = {
    "create_document",
    "fill_template",
    "apply_document_patch",
    "convert_document",
}


def _ctx(tmp_path: Path, cfg: Config | None = None) -> ToolContext:
    return ToolContext(cfg=cfg or {}, client=None, cwd=tmp_path)


def test_registry_exposes_document_tools_and_honors_disabled_group(
    tmp_path: Path,
) -> None:
    registry = build_registry(_ctx(tmp_path), include={"documents"})
    assert set(registry.names()) == NAMES
    assert all(
        spec["input_schema"]["properties"] is not None for spec in registry.specs()
    )

    blocked = build_registry(
        _ctx(tmp_path, {"disabled_tools": ["documents"]}),
        include={"documents"},
    )
    assert blocked.names() == []
    result = blocked.execute("inspect_document", {})
    assert result.is_error or "approval" in str(result.content).lower()


def test_registry_removes_direct_mutations_and_keeps_one_coordinator(
    tmp_path: Path,
) -> None:
    # Given: the canonical documents registry.
    registry = build_registry(_ctx(tmp_path), include={"documents"})

    # When: its public names are inspected.
    names = set(registry.names())

    # Then: only reads and the approval coordinator can reach Office work.
    assert names == NAMES
    assert names.isdisjoint(REMOVED_MUTATIONS)


def test_office_rollback_is_queued_for_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin import approvals
    from birkin.office import rollback_approval

    job_id = "a" * 32
    monkeypatch.setattr(
        rollback_approval,
        "prepare_rollback",
        lambda received: {
            "job_id": received,
            "destination": str(tmp_path / "result.docx"),
            "receipt_hmac": "a" * 64,
        },
    )
    proposed: list[dict[str, object]] = []

    def propose(**kwargs: object) -> dict[str, object]:
        proposed.append(kwargs)
        return {"id": "approval-1", "status": "pending"}

    monkeypatch.setattr(approvals, "propose", propose)
    registry = build_registry(_ctx(tmp_path), include={"documents"})

    result = registry.execute(
        "office_rollback_request",
        {"job_id": job_id},
    )

    assert not result.is_error
    assert proposed[0]["category"] == "office_rollback"
    assert proposed[0]["payload"] == {
        "job_id": job_id,
        "destination": str(tmp_path / "result.docx"),
        "receipt_hmac": "a" * 64,
    }


def test_document_tool_rejects_hashed_source_outside_dedicated_office_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    birkin_home = tmp_path / "home"
    birkin_home.mkdir()
    monkeypatch.setenv("BIRKIN_HOME", str(birkin_home))
    outside = _single_cell_xlsx(birkin_home / "vault.xlsx")
    digest = hashlib.sha256(outside.read_bytes()).hexdigest()
    registry = build_registry(_ctx(tmp_path), include={"documents"})

    result = registry.execute(
        "inspect_document",
        {"source": {"content_hash": digest, "uri": str(outside)}},
    )

    body = cast(dict[str, object], json.loads(cast(str, result.content)))
    error = cast(dict[str, object], body["error"])
    assert result.is_error
    assert error["code"] in {"PERMISSION_DENIED", "SOURCE_CHANGED"}
