from __future__ import annotations

from pathlib import Path

from birkin.tools import build_registry
from birkin.tools._types import Config, ToolContext

NAMES = {
    "list_document_adapters",
    "inspect_document",
    "extract_document",
    "compare_documents",
    "render_artifact",
    "validate_artifact",
    "office_job_request",
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
