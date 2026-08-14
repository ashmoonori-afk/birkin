import hashlib
from pathlib import Path
import pytest
from birkin.office.adapters.pdf import PdfAdapter
from birkin.office.errors import DocumentError,DocumentErrorCode
FIX=Path(__file__).parent/'fixtures/pdf/native-text.pdf'
def test_pdf_spans_have_page_bbox_hash_and_native_provenance():
    spans=PdfAdapter().extract(FIX); digest=hashlib.sha256(FIX.read_bytes()).hexdigest()
    assert spans and spans[0]['text']=='Hello PDF' and spans[0]['source_sha256']==digest and spans[0]['page_no']==1 and len(spans[0]['bbox'])==4 and spans[0]['method']=='pdf_text_operator'
    with pytest.raises(DocumentError) as caught: PdfAdapter().patch(FIX,{})
    assert caught.value.code is DocumentErrorCode.UNSUPPORTED_EDIT
