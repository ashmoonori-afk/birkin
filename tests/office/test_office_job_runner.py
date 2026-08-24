from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from birkin.office.export_policy import ExportRequest
from birkin.office.job import OfficeJob
from birkin.office.job_runner import DocumentServiceRunner
from birkin.office.service import DocumentService
from tests.office.fixture_builders import (
    build_docx_template,
    build_hwpx_template,
    build_pptx_template,
)

FORMATS = ("docx", "xlsx", "pptx", "hwpx")
OPERATIONS: dict[str, dict[str, object]] = {
    "docx": {"field": "customer", "value": "Dogfood DOCX modified"},
    "xlsx": {"cell": "A1", "value": 9},
    "pptx": {"placeholder_idx": 7, "value": "Dogfood PPTX modified"},
    "hwpx": {"field": "customer", "value": "Dogfood HWPX modified"},
}
EXPECTED_HISTORY = [
    "input_captured",
    "outcome_declared",
    "operations_proposed",
    "preview_ready",
    "approval_requested",
    "approved",
    "executed",
    "validated",
    "exported",
]


def _xlsx_fixture(path: Path) -> Path:
    parts = {
        "[Content_Types].xml": b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>',
        "xl/workbook.xml": b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><v>7</v></c></row></sheetData></worksheet>',
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)
    return path


def _source(home: Path, format_name: str) -> dict[str, str]:
    source = home / f"source.{format_name}"
    builders = {
        "docx": build_docx_template,
        "xlsx": _xlsx_fixture,
        "pptx": build_pptx_template,
        "hwpx": build_hwpx_template,
    }
    builders[format_name](source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return {
        "artifact_id": digest,
        "content_hash": digest,
        "media_type": "application/octet-stream",
        "uri": str(source.resolve()),
        "sensitivity": "internal",
        "acl_fingerprint": "contract-local",
    }


@pytest.mark.parametrize("format_name", FORMATS)
def test_document_service_runner_four_format_contract(
    tmp_path: Path, format_name: str
) -> None:
    service = DocumentService(tmp_path)
    source = _source(tmp_path, format_name)
    caller_folder = tmp_path / "caller-output"
    caller_folder.mkdir()
    job = OfficeJob(
        job_id=f"contract-{format_name}",
        format_name=format_name,
        source=source,
        runner=DocumentServiceRunner(service, export_root=caller_folder),
    )
    output_name = f"validated-{format_name}.{format_name}"
    output_path = service.home / "artifacts" / "drafts" / output_name
    destination = caller_folder / f"exported-{format_name}.{format_name}"
    source_path = Path(source["uri"])
    source_before = source_path.read_bytes()

    job.declare_outcome(f"Apply the proven {format_name} patch")
    job.propose_operations([OPERATIONS[format_name]])
    preview = job.build_preview()
    assert isinstance(preview["source_sha256"], str)
    before_approval = set((service.home / "artifacts" / "drafts").iterdir())
    _ = job.request_approval()
    assert not output_path.exists()
    assert set((service.home / "artifacts" / "drafts").iterdir()) == before_approval

    job.approve(actor="contract-test")
    execution = job.execute()
    draft = cast("Mapping[str, object]", execution["artifact"])
    assert Path(cast(str, draft["uri"])).is_file()
    validation = job.validate()
    assert isinstance(validation["status"], str)
    assert isinstance(validation["checks"], list)
    assert isinstance(validation["layers"], dict)
    publication = job.publish(output_name=output_name)
    assert job.state.value == "validated"
    exported = job.export(
        ExportRequest(
            destination=destination,
            actor="contract-test",
            proposal_digest=cast(str, job.receipt()["approval"]["proposal_digest"]),
            operations=(OPERATIONS[format_name],),
        )
    )

    receipt = job.receipt()
    history = cast("list[str]", receipt["history"])
    validated_path = Path(cast(str, publication["path"]))
    validated_before = validated_path.read_bytes()
    validated_sha256 = hashlib.sha256(validated_before).hexdigest()
    assert history == EXPECTED_HISTORY
    assert validated_path == output_path
    assert validated_path.parent == service.home / "artifacts" / "drafts"
    assert destination == Path(cast(str, exported["path"]))
    assert destination.read_bytes() == validated_path.read_bytes()
    assert source_path.read_bytes() == source_before
    assert publication["sha256"] == validated_sha256
    assert cast("Mapping[str, object]", receipt["export"])["output_sha256"] == validated_sha256
    rollback = job.rollback_export()
    assert rollback["restored"] is False
    assert not destination.exists()
    assert validated_path.read_bytes() == validated_before
    assert source_path.read_bytes() == source_before
    assert job.state.value == "validated"
    assert [state.value for state in job.history] == [*EXPECTED_HISTORY, "validated"]
    print(
        f"{format_name} history={history} "
        f"validated={validated_path} exported={destination} sha256={validated_sha256}"
    )
