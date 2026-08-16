import pytest

from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.xml_splice import resolve_text_span, splice_text

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


def test_splice_rejects_xml_control_characters():
    with pytest.raises(DocumentError) as caught:
        splice_text(
            XML,
            {"paragraph_native_id": "A", "run_index": 1},
            "invalid\x00value",
        )
    assert caught.value.code is DocumentErrorCode.INVALID_INPUT


def test_locator_rejects_duplicate_native_identity():
    duplicate = XML.replace(
        b'<w:p w14:paraId="B">',
        b'<w:p w14:paraId="A"><w:r><w:t>duplicate</w:t></w:r></w:p>'
        b'<w:p w14:paraId="B">',
    )

    with pytest.raises(DocumentError) as caught:
        resolve_text_span(duplicate, {"paragraph_native_id": "A", "run_index": 1})

    assert caught.value.code is DocumentErrorCode.AMBIGUOUS_LOCATOR


def test_locator_rejects_stale_expected_text():
    with pytest.raises(DocumentError) as caught:
        splice_text(
            XML,
            {
                "paragraph_native_id": "A",
                "run_index": 1,
                "expected_text": "previous value",
            },
            "replacement",
        )

    assert caught.value.code is DocumentErrorCode.PRECONDITION_FAILED


def test_locator_expected_text_matches_decoded_xml_text():
    escaped = XML.replace(b">one<", b">one &amp; two<")
    output = splice_text(
        escaped,
        {
            "paragraph_native_id": "A",
            "run_index": 1,
            "expected_text": "one & two",
        },
        "replacement",
    )

    assert b">replacement<" in output
