from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest

from birkin.tools import build_registry
from birkin.tools._types import Config, ToolContext
from tests.office.fixture_builders import build_docx_template

NAMES = {
    "list_document_adapters",
    "inspect_document",
    "extract_document",
    "create_document",
    "compare_documents",
    "fill_template",
    "apply_document_patch",
    "render_artifact",
    "validate_artifact",
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


def test_apply_tool_emits_only_a_managed_draft_and_preserves_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    source = build_docx_template(home / "template-fields.docx")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    before = source.read_bytes()
    registry = build_registry(_ctx(tmp_path), include={"documents"})
    payload = {
        "base": {
            "artifact_id": digest,
            "content_hash": digest,
            "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "uri": str(source),
            "sensitivity": "internal",
            "acl_fingerprint": "a" * 64,
        },
        "patch": {"operations": [{"field": "customer", "value": "Ada"}]},
        "expected_source_sha256": digest,
        "output_name": "draft.docx",
        "dry_run": False,
    }
    result = registry.execute("apply_document_patch", payload)
    assert isinstance(result.content, str)
    body = cast("dict[str, object]", json.loads(result.content))
    assert not result.is_error, body
    artifact = cast("dict[str, str]", body["draft_artifact"])
    assert Path(artifact["uri"]).is_file()
    assert source.read_bytes() == before

    rendered = registry.execute("render_artifact", {"artifact": payload["base"]})
    assert isinstance(rendered.content, str)
    unavailable = cast("dict[str, object]", json.loads(rendered.content))
    error = cast("dict[str, object]", unavailable["error"])
    assert error["code"] == "CAPABILITY_UNAVAILABLE"
