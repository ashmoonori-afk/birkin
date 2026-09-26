from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.operation_targets import ResolvedTarget
from birkin.office.presentation import format_preview_replacement
from birkin.office.preview_semantics import PreviewSummary, summarize_operations
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


def test_resolved_targets_describe_field_operations_without_preview_nodes() -> None:
    # Given: exact targets replayed by the apply-time resolvers, one clearing a field.
    preview = {"preview": {"nodes": []}}
    operations = [
        {"field": "customer", "value": "홍길동"},
        {"field": "date", "value": ""},
    ]
    resolved = [
        ResolvedTarget("hwpx field customer", "PLACEHOLDER"),
        ResolvedTarget("hwpx field date", "2026-09-01"),
    ]

    # When: the operations are summarized with those targets.
    summaries = summarize_operations(preview, operations, resolved=resolved)

    # Then: each summary is exact and an empty value survives.
    assert summaries == [
        {"location": "hwpx field customer", "before": "PLACEHOLDER", "after": "홍길동"},
        {"location": "hwpx field date", "before": "2026-09-01", "after": ""},
    ]


@pytest.mark.parametrize(
    ("location", "before", "after", "expected"),
    [
        ("docx paragraph 2", "A", "B", "DOCX 2번째 문단 변경: A → B"),
        ("pptx slide_paragraph 3", "A", "B", "PPTX 3번째 문단 변경: A → B"),
        (
            "docx field customer",
            "PLACEHOLDER",
            "홍길동",
            "DOCX 필드 'customer' 변경: PLACEHOLDER → 홍길동",
        ),
        ("hwpx field date", "", "2026-09-26", "HWPX 필드 'date' 변경: (빈 값) → 2026-09-26"),
        ("pptx slide 2 placeholder 1", "본문", "새 본문", "슬라이드 2 개체 틀 1 변경: 본문 → 새 본문"),
        ("Revenue!B2", "42", "77", "Revenue!B2 변경: 42 → 77"),
        ("docx field customer", "A", "", "DOCX 필드 'customer' 변경: A → (빈 값)"),
    ],
)
def test_replacement_locations_are_translated_for_the_korean_review_surface(
    location: str, before: str, after: str, expected: str
) -> None:
    summary: PreviewSummary = {"location": location, "before": before, "after": after}

    assert format_preview_replacement(summary) == expected
