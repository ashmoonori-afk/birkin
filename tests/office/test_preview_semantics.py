from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.presentation import format_preview_replacement
from birkin.office.preview_semantics import summarize_operations
from birkin.office.service import DocumentService


def test_summaries_describe_each_cell_replacement_from_structured_nodes() -> None:
    # Given: a structured preview with a machine-readable spreadsheet cell locator.
    preview = {
        "preview": {
            "nodes": [
                {
                    "kind": "cell",
                    "text": "42",
                    "source_locator": {
                        "format": "xlsx",
                        "sheet": "Revenue",
                        "cell": "B2",
                    },
                }
            ]
        }
    }
    operations = [{"cell": "B2", "value": 77}]

    # When: the cell operation is summarized.
    summaries = summarize_operations(preview, operations)

    # Then: machine data stays structured until the Korean presentation boundary.
    assert summaries == [
        {
            "location": "Revenue!B2",
            "before": "42",
            "after": "77",
        }
    ]
    assert format_preview_replacement(summaries[0]) == (
        "Revenue!B2 변경: 42 → 77"
    )


def test_summaries_use_a_real_structured_preview_for_paragraph_replacements(
    tmp_path: Path,
) -> None:
    # Given: the existing renderer's structured DOCX preview and a paragraph locator.
    source = tmp_path / "preview.docx"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            b"".join(
                (
                    b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
                    b'<Override PartName="/word/document.xml" ',
                    b'ContentType="application/vnd.openxmlformats-officedocument.',
                    b'wordprocessingml.document.main+xml"/></Types>',
                )
            ),
        )
        archive.writestr(
            "word/document.xml",
            b"".join(
                (
                    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">',
                    b"<w:p><w:r><w:t>Heading</w:t></w:r></w:p>",
                    b"<w:p><w:r><w:t>Original paragraph</w:t></w:r></w:p>",
                    b"</w:document>",
                )
            ),
        )
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    artifact = {"uri": str(source), "content_hash": digest}
    preview = DocumentService(tmp_path).render_artifact(
        artifact, output_format="structured_preview"
    )
    operations = [
        {"locator": {"format": "docx", "index": 2}, "value": "Revised paragraph"}
    ]

    # When: the proposed paragraph replacement is summarized.
    summaries = summarize_operations(preview, operations)

    # Then: its location and before/after values are preserved without a renderer error.
    assert len(summaries) == len(operations)
    assert summaries == [
        {
            "location": "docx paragraph 2",
            "before": "Original paragraph",
            "after": "Revised paragraph",
        }
    ]


@pytest.mark.parametrize(
    "operations",
    [
        [{"cell": "B2", "value": 77}, {"cell": "C2", "value": 88}],
        [{"field": "customer", "value": "Ada"}],
    ],
)
def test_summaries_fail_closed_when_operations_cannot_match_preview_nodes(
    operations: list[dict[str, int | str]],
) -> None:
    # Given: one source node that cannot prove every requested replacement.
    preview = {
        "preview": {
            "nodes": [
                {
                    "kind": "cell",
                    "text": "42",
                    "source_locator": {"format": "xlsx", "cell": "B2"},
                }
            ]
        }
    }

    # When: unmatched or unsupported operations are summarized.
    with pytest.raises(DocumentError) as caught:
        _ = summarize_operations(preview, operations)

    # Then: the semantic preview refuses to invent values.
    assert caught.value.code is DocumentErrorCode.PRECONDITION_FAILED
