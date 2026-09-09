from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from docx import Document

from birkin import approvals
from birkin.data_controls import status
from birkin.office.search import search_sources
from birkin.office.service import DocumentService
from birkin.tools import build_registry
from birkin.tools._types import ToolContext


def test_data_controls_distinguish_storage_and_delete_only_hashed_work_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    source = home / "office" / "sources" / "report.docx"
    source.parent.mkdir(parents=True)
    document = Document()
    document.add_paragraph("retention canary")
    document.save(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setenv("BIRKIN_HOME", str(home))

    controls = status({"memory_enabled": True})
    assert controls["storage_classes"]["original"]["birkin_deletes"] is False
    assert controls["storage_classes"]["memory"]["deletion"] == "logical archive"
    before = search_sources("retention", [{
        "artifact": {"uri": str(source), "content_hash": digest}, "scope": "current_work",
        "access_granted": True, "version": "v1",
    }], extract=DocumentService(home / "office").extract_document)
    assert before["results"]

    registry = build_registry(ToolContext(cfg={}, client=None, cwd=tmp_path), include={"connections"})
    proposal = registry.execute("data_work_copy_delete_request", {
        "name": source.name, "uri": str(source), "content_hash": digest,
    })
    approval_id = json.loads(str(proposal.content))["id"]
    approved = approvals.approve(approval_id, approved_by="user:test", approved_via="test")
    receipt = json.loads(str(approved["result"]))
    assert approved["ok"] is True and receipt["physical_deleted"] is True
    assert not source.exists()

    after = search_sources("retention", [{
        "artifact": {"uri": str(source), "content_hash": digest}, "scope": "current_work",
        "access_granted": True, "version": "v1",
    }], extract=DocumentService(home / "office").extract_document)
    assert after["results"] == [] and after["excluded_sources"] == 1


def test_data_delete_refuses_original_outside_office_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    original = tmp_path / "original.docx"
    original.write_bytes(b"original")
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    from birkin.data_controls import delete_work_copy

    with pytest.raises(PermissionError, match="work copy"):
        delete_work_copy({"uri": str(original), "content_hash": digest})
    assert original.exists()
