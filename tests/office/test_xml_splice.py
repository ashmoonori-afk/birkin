import pytest
from birkin.office.errors import DocumentError,DocumentErrorCode
from birkin.office.xml_splice import splice_text,resolve_text_span
XML=b'<w:document xmlns:w="w" xmlns:x="urn:x"><w:p w14:paraId="A"><w:r><w:t>one</w:t></w:r><x:opaque a=" 1 ">keep</x:opaque></w:p><w:p w14:paraId="B"><w:r><w:t>two</w:t></w:r></w:p></w:document>'
def test_splice_preserves_every_byte_outside_target_span():
    start,end=resolve_text_span(XML,{'paragraph_native_id':'A','run_index':1}); out=splice_text(XML,{'paragraph_native_id':'A','run_index':1},'changed & safe')
    replacement=b'changed &amp; safe'
    assert out[:start]==XML[:start] and out[start+len(replacement):]==XML[end:] and b'<x:opaque a=" 1 ">keep</x:opaque>' in out
def test_native_identity_survives_a_preceding_insert():
    changed=XML.replace(b'<w:p w14:paraId="B">',b'<w:p w14:paraId="X"><w:r><w:t>new</w:t></w:r></w:p><w:p w14:paraId="B">')
    assert b'two' in changed[slice(*resolve_text_span(changed,{'paragraph_native_id':'B','run_index':1}))]
    with pytest.raises(DocumentError) as caught: resolve_text_span(changed,{'paragraph_index':2,'run_index':1})
    assert caught.value.code in {DocumentErrorCode.AMBIGUOUS_LOCATOR,DocumentErrorCode.PRECONDITION_FAILED}
