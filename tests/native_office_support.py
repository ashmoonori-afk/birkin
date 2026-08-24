from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

from docx import Document

from birkin import approvals
from birkin.tools import build_registry
from birkin.tools._types import ToolContext


def approved_docx(home: Path, index: int = 0) -> dict[str, object]:
    """Create a source fixture, then mutate it only through canonical approval."""
    home.mkdir(parents=True, exist_ok=True)
    export_root = home / "exports"
    export_root.mkdir(exist_ok=True)
    source = home / f"native-source-{index}.docx"
    destination = export_root / f"native-approved-{index}.docx"
    document = Document()
    _ = document.add_paragraph(f"Native Office source {index}")
    document.save(str(source))
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    registry = build_registry(
        ToolContext(
            cfg={},
            client=None,
            cwd=export_root,
            record_source="user:native-office-test",
        ),
        include={"documents"},
    )
    proposed = registry.execute(
        "office_job_request",
        {
            "request": "Update this Word document",
            "source": {"content_hash": source_hash, "uri": str(source)},
            "outcome": "Replace the source paragraph",
            "operations": [
                {
                    "locator": {"format": "docx", "index": 1},
                    "value": f"Approved native Office document {index}",
                }
            ],
            "destination": str(destination),
        },
    )
    body = cast(dict[str, object], json.loads(cast(str, proposed.content)))
    assert proposed.is_error is False, body
    approved = approvals.approve(cast(str, body["id"]))
    assert approved["ok"] is True, approved
    output_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
    return {
        "artifact_id": output_hash,
        "content_hash": output_hash,
        "media_type": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        "uri": str(destination),
        "sensitivity": "internal",
        "acl_fingerprint": "native-office-test",
    }
