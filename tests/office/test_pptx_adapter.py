import zipfile
from pathlib import Path

from birkin.office.adapters.pptx import PptxAdapter
from tests.office.fixture_builders import build_pptx_template


def test_pptx_run_patch_keeps_slide_master_placeholder_notes_and_unknown_parts(
    tmp_path: Path,
) -> None:
    source = build_pptx_template(tmp_path / "branded-placeholder.pptx")
    adapter = PptxAdapter()
    before = adapter.part_hashes(source)
    output = tmp_path / "draft.pptx"
    _ = adapter.patch_placeholder(source, output, 7, "New title")
    after = adapter.part_hashes(output)
    preserved = (
        "ppt/slideMasters/slideMaster1.xml",
        "ppt/slideLayouts/slideLayout1.xml",
        "ppt/notesSlides/notesSlide1.xml",
        "ppt/theme/theme1.xml",
        "ppt/media/logo.bin",
        "custom/opaque.xml",
    )
    for part in preserved:
        assert before[part] == after[part]
    with zipfile.ZipFile(output) as archive:
        slide = archive.read("ppt/slides/slide1.xml")
    assert b"New title" in slide
    assert b"PLACEHOLDER" not in slide
