import hashlib, zipfile
import pytest
from birkin.office.errors import DocumentError,DocumentErrorCode
from birkin.office.package import clone_package,preflight_package

def _zip(path, entries):
    with zipfile.ZipFile(path,'w') as z:
        for name,data in entries: z.writestr(name,data)
def test_clone_replaces_one_known_part_and_preserves_unknown_part_bytes(tmp_path):
    src=tmp_path/'source.docx'; _zip(src,[('[Content_Types].xml',b'<Types/>'),('word/document.xml',b'<doc>old</doc>'),('custom/opaque.bin',b'\x00opaque')])
    before=hashlib.sha256(src.read_bytes()).hexdigest(); out=tmp_path/'draft.docx'
    manifest=clone_package(src,out,{'word/document.xml':b'<doc>new</doc>'})
    with zipfile.ZipFile(out) as z: assert z.read('custom/opaque.bin')==b'\x00opaque' and z.read('word/document.xml')==b'<doc>new</doc>'
    assert manifest['parts']['custom/opaque.bin']['original_sha256']==hashlib.sha256(b'\x00opaque').hexdigest()
    assert hashlib.sha256(src.read_bytes()).hexdigest()==before
def test_preflight_rejects_traversal_and_dtd_with_typed_codes(tmp_path):
    for name,entries in [('bad.docx',[('../evil',b'x')]),('dtd.docx',[('word/document.xml',b'<!DOCTYPE x><x/>')])]:
        path=tmp_path/name; _zip(path,entries)
        with pytest.raises(DocumentError) as caught: preflight_package(path)
        assert caught.value.code is DocumentErrorCode.PACKAGE_INVALID
