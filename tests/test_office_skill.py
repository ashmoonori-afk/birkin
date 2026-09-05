from __future__ import annotations

from pathlib import Path
from typing import cast

from birkin.skills.loader import Skill, discover
from birkin.skills.validate import validate_skill
from birkin.tools import build_registry
from birkin.tools._types import ToolContext
from birkin.tools.documents import NAMES

SKILL_ROOT = Path("skills/productivity")
ROUTES = {
    "office-work-os": ["docx", "xlsx", "pptx", "pdf", "hwpx"],
    "office-documents": ["docx", "xlsx", "pptx", "pdf", "hwpx"],
    "word-documents": ["docx"],
    "spreadsheets": ["xlsx"],
    "presentations": ["pptx"],
    "pdf-documents": ["pdf"],
    "korean-hwp-documents": ["hwpx"],
}
TOOLS = set(NAMES)
REQUIRED_ARGUMENTS = {
    "list_document_adapters": [],
    "inspect_document": ["source"],
    "extract_document": ["source"],
    "analyze_workbook": ["source", "sheet", "cell_range"],
    "review_meeting_actions": ["notes", "candidates"],
    "list_work_items": [],
    "work_item_request": ["action"],
    "search_office_sources": ["query", "sources"],
    "list_office_batches": [],
    "office_batch_request": [],
    "compare_documents": ["left", "right"],
    "render_artifact": ["artifact"],
    "validate_artifact": ["artifact"],
    "office_job_request": [
        "request",
        "outcome",
        "destination",
    ],
    "office_rollback_request": ["job_id"],
}
SENTINEL_SECTIONS = {
    "When to Use",
    "Trigger",
    "Non-triggers",
    "Supported/Unsupported Matrix",
    "Read Before Write",
    "Backup/Copy-on-Write",
    "Exact Tool Calls",
    "Typed Examples",
    "Pitfalls",
    "Verification",
    "Failure Recovery",
    "Security Warnings",
}


def _birkin_metadata(skill: Skill) -> dict[str, object]:
    metadata_root = cast(dict[str, object], skill.meta["metadata"])
    return cast(dict[str, object], metadata_root["birkin"])


def test_malformed_skill_does_not_block_valid_discovery(tmp_path: Path):
    malformed = tmp_path / "malformed" / "SKILL.md"
    malformed.parent.mkdir()
    malformed.write_text(
        "---\nitems:\n  - first\n  broken: value\n---\n",
        encoding="utf-8",
    )
    valid = tmp_path / "valid" / "SKILL.md"
    valid.parent.mkdir()
    valid.write_text(
        "---\nname: valid-skill\ndescription: usable\n---\n",
        encoding="utf-8",
    )

    found = discover([(tmp_path, "extra")])

    assert set(found) == {"malformed", "valid-skill"}


def test_office_bundle_validates_and_declares_machine_contract() -> None:
    discovered = discover([(Path("skills"), "bundled")])

    for name, formats in ROUTES.items():
        skill = discovered[name]
        report = validate_skill(skill.path, source="bundled")
        assert report.ok, report.errors

        metadata = _birkin_metadata(skill)
        assert cast(list[str], metadata["formats"]) == formats
        assert set(cast(list[str], metadata["requires_tools"])) == TOOLS
        assert metadata["inspect_first"] == "inspect_document"
        assert metadata["write_policy"] == "copy-on-write"
        assert metadata["extension_conversion"] == "txt-only"

        headings = {
            line.removeprefix("## ")
            for line in skill.body().splitlines()
            if line.startswith("## ")
        }
        assert SENTINEL_SECTIONS <= headings

    expected_routes = {
        "docx": "word-documents",
        "xlsx": "spreadsheets",
        "pptx": "presentations",
        "pdf": "pdf-documents",
        "hwpx": "korean-hwp-documents",
    }
    root_metadata = _birkin_metadata(discovered["office-work-os"])
    dispatcher_metadata = _birkin_metadata(discovered["office-documents"])
    assert root_metadata["dispatcher"] == "office-documents"
    assert root_metadata["routes"] == expected_routes
    assert dispatcher_metadata["routes"] == expected_routes


def test_office_skill_tool_contract_matches_registered_document_tools(
    tmp_path: Path,
) -> None:
    registry = build_registry(
        ToolContext(cfg={}, client=None, cwd=tmp_path), include={"documents"}
    )
    specs = {spec["name"]: spec["input_schema"] for spec in registry.specs()}

    assert TOOLS <= set(specs)
    assert {
        name: cast(dict[str, object], specs[name])["required"]
        for name in TOOLS
    } == REQUIRED_ARGUMENTS
    office_job = cast(dict[str, object], specs["office_job_request"])
    assert office_job["oneOf"] == [
        {"required": ["source", "operations"]},
        {"required": ["format", "content"]},
    ]

    extract_properties = cast(
        dict[str, object], cast(dict[str, object], specs["extract_document"])["properties"]
    )
    render_properties = cast(
        dict[str, object], cast(dict[str, object], specs["render_artifact"])["properties"]
    )
    output_format = cast(dict[str, object], render_properties["output_format"])
    assert "max_text_bytes" in extract_properties
    assert output_format["enum"] == ["structured_preview", "pdf", "png", "thumbnail"]
