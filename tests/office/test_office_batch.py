from __future__ import annotations

import json
from pathlib import Path

from birkin.office import batch
from birkin.office.coordinator import OfficeCaller


def test_batch_keeps_partial_results_and_retries_failed_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    sources = []
    items = []
    for index in range(2):
        source = tmp_path / "office" / f"source-{index}.docx"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(f"source-{index}".encode())
        sources.append(source)
        items.append({"request": "Update Word document", "source": {"uri": str(source)}, "outcome": "update", "operations": [{"op": "x"}], "destination": str(tmp_path / f"out-{index}.docx")})
    monkeypatch.setattr(batch.OfficeCoordinator, "request", lambda self, request: {"destination": str(request.destination), "job_id": request.destination.stem})
    prepared = batch.prepare(items, OfficeCaller(tmp_path, "test"))

    def execute_one(plan, **kwargs):
        if plan["job_id"] == "out-1":
            raise RuntimeError("broken")
        return json.dumps({"job_id": plan["job_id"]})

    monkeypatch.setattr(batch, "execute_approved_office_job", execute_one)
    result = json.loads(batch.execute(prepared, approval_id="approval-1"))

    assert result["status"] == "partial_failed" and result["succeeded"] == 1 and result["failed"] == 1
    retry = batch.prepare([], OfficeCaller(tmp_path, "test"), retry_of=prepared["batch_id"])
    assert len(retry["plans"]) == 1 and retry["requests"][0]["destination"].endswith("out-1.docx")
