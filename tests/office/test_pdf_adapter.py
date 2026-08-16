from pathlib import Path

import pytest

from birkin.office.adapters.pdf import PdfAdapter
from birkin.office.errors import DocumentError, DocumentErrorCode

FIX = Path(__file__).parent / "fixtures/pdf/native-text.pdf"


def test_xref_less_legacy_pdf_is_rejected_by_strict_parser() -> None:
    before = FIX.read_bytes()
    with pytest.raises(DocumentError) as caught:
        _ = PdfAdapter().extract(FIX)
    assert caught.value.code is DocumentErrorCode.PACKAGE_INVALID
    assert caught.value.details["reason"] == "pdf_structure_invalid"
    assert FIX.read_bytes() == before

    with pytest.raises(DocumentError) as patched:
        PdfAdapter().patch(FIX, {"type": "body_edit"})
    assert patched.value.code is DocumentErrorCode.PACKAGE_INVALID
