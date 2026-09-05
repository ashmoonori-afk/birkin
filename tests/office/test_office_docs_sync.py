from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

from birkin.office.adapters.catalog import adapter_inventory
from birkin.tools.documents import NAMES

ROOT = Path(__file__).parents[2]
README_PATHS = (
    ROOT / "README.md",
    ROOT / "README.ko.md",
)
DOC_PATHS = (*README_PATHS, ROOT / "docs" / "office-support.md")
SKILL_IDS = (
    "office-work-os",
    "office-documents",
    "word-documents",
    "spreadsheets",
    "presentations",
    "pdf-documents",
    "korean-hwp-documents",
)
EXPECTED_MATRIX = {
    "docx": (
        "bounded",
        "conditional",
        "bounded",
        "structural",
        "layered",
        "bounded",
        "bounded",
        "structured-preview",
    ),
    "xlsx": (
        "bounded",
        "conditional",
        "bounded",
        "structural",
        "layered",
        "bounded",
        "bounded",
        "structured-preview",
    ),
    "pptx": (
        "bounded",
        "conditional",
        "bounded",
        "structural",
        "layered",
        "bounded",
        "bounded",
        "structured-preview",
    ),
    "pdf": (
        "bounded",
        "bounded",
        "conditional",
        "structural",
        "layered",
        "conditional",
        "refused",
        "structured-preview",
    ),
    "hwpx": (
        "bounded",
        "conditional",
        "bounded",
        "structural",
        "layered",
        "bounded",
        "bounded",
        "structured-preview",
    ),
}
MATRIX_START = "<!-- office-support-matrix:start -->"
MATRIX_END = "<!-- office-support-matrix:end -->"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _matrix(text: str) -> dict[str, tuple[str, ...]]:
    block = text.split(MATRIX_START, 1)[1].split(MATRIX_END, 1)[0]
    rows: dict[str, tuple[str, ...]] = {}
    for line in block.splitlines():
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if cells and cells[0] in EXPECTED_MATRIX:
            rows[cells[0]] = tuple(cells[1:])
    return rows


def _project_version() -> str:
    match = re.search(
        r'^version = "([^"]+)"$',
        _text(ROOT / "pyproject.toml"),
        flags=re.MULTILINE,
    )
    assert match is not None
    return match.group(1)


def _skill_name(path: Path) -> str:
    match = re.search(r"^name: ([a-z0-9-]+)$", _text(path), flags=re.MULTILINE)
    assert match is not None
    return match.group(1)


def test_support_matrix_rows_and_statuses_match_runtime_contract() -> None:
    matrices = [_matrix(_text(path)) for path in DOC_PATHS]
    assert all(matrix == EXPECTED_MATRIX for matrix in matrices)
    assert set(EXPECTED_MATRIX) == {item["format"] for item in adapter_inventory()}


def test_docs_publish_current_tool_arguments_and_workspace_boundary() -> None:
    for path in DOC_PATHS:
        text = _text(path)
        office_contract = text.split("Office Work OS v2", 1)[1]
        if "## GitHub Action" in office_contract:
            office_contract = office_contract.split("## GitHub Action", 1)[0]
        assert ".omo/" not in text, path
        assert "max_chars" not in office_contract, path
        assert "max_text_bytes" in text, path
        assert "loss_budget" in text, path
        assert "/workspace/.birkin/" in text, path
        assert "structured_preview" in text, path
        assert "RENDER_UNAVAILABLE" in text, path
        assert "public_entrypoint" in text, path


def test_registered_tool_and_skill_identifiers_are_documented() -> None:
    documented = [_text(path) for path in DOC_PATHS]
    assert all(all(f"`{name}`" in text for name in NAMES) for text in documented)
    assert all(all(f"`{skill_id}`" in text for skill_id in SKILL_IDS) for text in documented)

    skill_paths = tuple(
        ROOT / "skills" / "productivity" / skill_id / "SKILL.md"
        for skill_id in SKILL_IDS
    )
    assert tuple(_skill_name(path) for path in skill_paths) == SKILL_IDS


def test_version_and_provenance_publications_are_synchronized() -> None:
    manifest_path = ROOT / "birkin" / "office" / "adapters" / "provenance_manifest.json"
    manifest = cast(dict[str, object], json.loads(_text(manifest_path)))
    version = _project_version()
    required = (
        f"`{version}`",
        f"`catalog_revision: {manifest['catalog_revision']}`",
        f"`inventory_sha256: {manifest['inventory_sha256']}`",
        "provenance_manifest.json",
        "THIRD_PARTY_NOTICES.md",
    )
    for path in README_PATHS:
        text = _text(path)
        assert all(value in text for value in required), path

    assert manifest["inventory"] == adapter_inventory()


def test_detailed_office_support_version_matches_project() -> None:
    version = _project_version()
    detail = _text(ROOT / "docs" / "office-support.md")
    assert f"- Birkin version: `{version}`" in detail


def test_english_and_korean_windows_publication_claims_match() -> None:
    claims = (
        "development preview",
        "installer and updater delivery",
        "production\nsigning",
        "provider-backed production delivery",
    )
    english = _text(ROOT / "README.md").lower()
    korean = _text(ROOT / "README.ko.md").lower()
    assert all(claim in english for claim in claims)
    assert "development preview" in korean
    assert "installer와 updater delivery" in korean
    assert "production signing" in korean
    assert "provider-backed production delivery" in korean


def test_office_document_links_and_anchor_targets_exist() -> None:
    readmes = (_text(ROOT / "README.md"), _text(ROOT / "README.ko.md"))
    for text in readmes:
        match = re.search(r"\]\(\./docs/office-support\.md#([^)]+)\)", text)
        assert match is not None
        anchor = match.group(1)
        heading_matches = cast(
            list[str],
            re.findall(
                r"^#+\s+(.+)$",
                _text(ROOT / "docs" / "office-support.md"),
                re.MULTILINE,
            ),
        )
        headings: set[str] = set()
        for heading in heading_matches:
            normalized = re.sub(r"[^\w -]", "", heading, flags=re.UNICODE)
            headings.add(normalized.strip().lower().replace(" ", "-"))
        assert anchor in headings

    detail = _text(ROOT / "docs" / "office-support.md")
    local_links = cast(
        list[str], re.findall(r"\[[^]]+\]\((\.\.?/[^)#]+)(?:#[^)]+)?\)", detail)
    )
    assert local_links
    for target in local_links:
        assert (ROOT / "docs" / target).resolve().exists()
