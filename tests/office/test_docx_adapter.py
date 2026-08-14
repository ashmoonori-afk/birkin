import hashlib,zipfile
from pathlib import Path
from birkin.office.adapters.docx import DocxAdapter
FIX=Path(__file__).parent/'fixtures/docx/template-fields.docx'
def test_docx_round_trip_edits_one_field_and_preserves_unknown_subtree(tmp_path):
    adapter=DocxAdapter(); info=adapter.inspect(FIX)
    assert {'paragraphs','tables','headers','styles'} <= info.keys()
    out=tmp_path/'draft.docx'; before=adapter.part_hashes(FIX); adapter.patch_field(FIX,out,'customer','Ada')
    after=adapter.part_hashes(out); assert before['custom/opaque.xml']==after['custom/opaque.xml']
    with zipfile.ZipFile(out) as z: assert b'Ada' in z.read('word/document.xml') and b'PLACEHOLDER' not in z.read('word/document.xml')
