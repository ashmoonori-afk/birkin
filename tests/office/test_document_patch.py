import hashlib
import zipfile

import pytest

from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.patches import PatchOperation, apply_patch
from birkin.office.templates import bind_template


def test_patch_is_copy_first_atomic_and_precondition_bound(tmp_path):
    src=tmp_path/'source.docx'
    with zipfile.ZipFile(src,'w') as z:z.writestr(
        'word/document.xml',
        b'<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        b'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
        b'w14:paraId="A"><w:t>old</w:t></w:p>',
    )
    digest=hashlib.sha256(src.read_bytes()).hexdigest(); out=tmp_path/'draft.docx'
    ops=[PatchOperation('word/document.xml',{'paragraph_native_id':'A','run_index':1},'new',digest),PatchOperation('word/document.xml',{'paragraph_native_id':'A','run_index':1},'again','0'*64)]
    with pytest.raises(DocumentError) as caught: apply_patch(src,out,ops,expected_source_sha256=digest)
    assert caught.value.code is DocumentErrorCode.PRECONDITION_FAILED and not out.exists() and hashlib.sha256(src.read_bytes()).hexdigest()==digest
    result=apply_patch(src,out,ops[:1],expected_source_sha256=digest); assert out.exists() and result!=digest and hashlib.sha256(src.read_bytes()).hexdigest()==digest
def test_strict_template_binding_rejects_missing_duplicate_and_raw_fallback():
    fields=[{'key':'name','kind':'native','locator':{'id':'1'}},{'key':'name','kind':'raw','locator':{'id':'2'}}]
    assert bind_template(fields,{'name':'Ada'},strict=True)[0]['locator']=={'id':'1'}
    with pytest.raises(DocumentError): bind_template([],{'name':'Ada'},strict=True)
    with pytest.raises(DocumentError): bind_template([{'key':'x','kind':'raw','locator':{}}],{'x':'v'},raw_token_fallback=False)
