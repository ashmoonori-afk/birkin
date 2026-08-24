from __future__ import annotations

from pathlib import Path

from script.qa import office_base_wheel_smoke


def test_base_wheel_smoke_consumes_current_dogfood_layout(tmp_path: Path) -> None:
    # Given: the paths emitted by the current Office dogfood producer.
    sources = tmp_path / "sources"
    drafts = tmp_path / "artifacts" / "drafts"
    sources.mkdir(parents=True)
    drafts.mkdir(parents=True)
    expected = {
        "docx": drafts / "created-docx.docx",
        "xlsx": drafts / "created-xlsx.xlsx",
        "pptx": drafts / "created-pptx.pptx",
        "pdf": drafts / "created-pdf.pdf",
        "hwpx": sources / "source.hwpx",
    }
    for path in expected.values():
        path.touch()

    # When: the base-wheel driver selects its real-document fixtures.
    selected = office_base_wheel_smoke.fixture_sources(tmp_path)

    # Then: every format resolves to the producer's machine-consumed artifact.
    assert selected == expected
