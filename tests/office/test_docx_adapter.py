import zipfile
from pathlib import Path

from birkin.office.adapters.docx import DocxAdapter
from tests.office.fixture_builders import build_docx_template


def test_docx_round_trip_edits_one_field_and_preserves_unknown_subtree(
    tmp_path: Path,
) -> None:
    source = build_docx_template(tmp_path / "template-fields.docx")
    adapter = DocxAdapter()
    info = adapter.inspect(source)
    assert {"paragraphs", "tables", "headers", "styles"} <= info.keys()
    output = tmp_path / "draft.docx"
    before = adapter.part_hashes(source)
    _ = adapter.patch_field(source, output, "customer", "Ada")
    after = adapter.part_hashes(output)
    assert before["custom/opaque.xml"] == after["custom/opaque.xml"]
    with zipfile.ZipFile(output) as archive:
        document = archive.read("word/document.xml")
    assert b"Ada" in document
    assert b"PLACEHOLDER" not in document
