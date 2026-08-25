from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from birkin.office.adapters import pdf_state
from birkin.office.errors import DocumentError, DocumentErrorCode


def _assert_limit(error: pytest.ExceptionInfo[DocumentError], reason: str) -> None:
    assert error.value.code is DocumentErrorCode.LIMIT_EXCEEDED
    assert error.value.details["reason"] == reason


def test_pdf_file_limit_applies_before_parser_import(tmp_path: Path) -> None:
    source = tmp_path / "large.pdf"
    source.write_bytes(b"%PDF-" + (b"x" * 20))

    with pytest.raises(DocumentError) as caught:
        pdf_state.inspect_pdf(
            source,
            limits=pdf_state.PDFLimits(max_file_bytes=10),
        )

    _assert_limit(caught, "pdf_file_bytes")


def test_pdf_page_limit_applies_before_page_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "pages.pdf"
    source.write_bytes(b"%PDF-test")
    reader = SimpleNamespace(
        is_encrypted=False,
        pages=[object(), object()],
        root_object={},
        user_access_permissions=None,
    )
    monkeypatch.setattr(pdf_state, "_reader", lambda _path, _password: reader)

    with pytest.raises(DocumentError) as caught:
        pdf_state.inspect_pdf(
            source,
            limits=pdf_state.PDFLimits(max_pages=1),
        )

    _assert_limit(caught, "pdf_pages")


def test_pdf_defaults_cap_pages_and_sample_inspection_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")
    calls = [0] * 6

    class Page:
        def __init__(self, index: int) -> None:
            self.index = index

        def extract_text(self) -> str:
            calls[self.index] += 1
            return f"page-{self.index}"

        def __contains__(self, _key: object) -> bool:
            return False

        def get(self, _key: object, default: object = None) -> object:
            return default

        def items(self):
            return ().__iter__()

        def values(self):
            return ().__iter__()

    pages = [Page(index) for index in range(6)]
    reader = SimpleNamespace(
        is_encrypted=False,
        pages=pages,
        root_object={},
        user_access_permissions=None,
    )
    monkeypatch.setattr(pdf_state, "_reader", lambda _path, _password: reader)
    monkeypatch.setattr(pdf_state, "permission_validity", lambda _reader: None)
    monkeypatch.setattr(pdf_state, "images_on_page", lambda _page: 0)
    monkeypatch.setattr(
        pdf_state,
        "inventory",
        lambda _document, _size: ([], []),
    )

    _state, parsed = pdf_state.inspect_pdf(source)

    assert pdf_state.DEFAULT_PDF_LIMITS.max_pages == 200
    assert calls == [1, 1, 1, 1, 1, 0]
    _ = [page.extract_text() for page in parsed.pages]
    assert calls == [1, 1, 1, 1, 1, 1]


@pytest.mark.parametrize(
    ("text", "images", "limits", "reason"),
    [
        (
            "oversized text",
            0,
            {"max_text_bytes": 4},
            "pdf_text_bytes",
        ),
        (
            "",
            2,
            {"max_images": 1},
            "pdf_images",
        ),
    ],
)
def test_pdf_content_limits_stop_during_single_page_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    images: int,
    limits: dict[str, int],
    reason: str,
) -> None:
    source = tmp_path / "content.pdf"
    source.write_bytes(b"%PDF-test")
    page = SimpleNamespace(extract_text=lambda: text)
    page.with_cached_text = lambda _text: page
    reader = SimpleNamespace(
        is_encrypted=False,
        pages=[object()],
        root_object={},
        user_access_permissions=None,
    )
    monkeypatch.setattr(pdf_state, "_reader", lambda _path, _password: reader)
    monkeypatch.setattr(
        pdf_state.ParsedPage,
        "from_object",
        lambda _value: page,
    )
    monkeypatch.setattr(pdf_state, "permission_validity", lambda _reader: None)
    monkeypatch.setattr(pdf_state, "images_on_page", lambda _page: images)

    with pytest.raises(DocumentError) as caught:
        pdf_state.inspect_pdf(
            source,
            limits=pdf_state.PDFLimits(**limits),
        )

    _assert_limit(caught, reason)
