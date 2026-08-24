from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import cast

import pytest

from birkin.office import extract_package
from birkin.office.adapters import xlsx
from birkin.office.adapters.ooxml_surgery import element_blocks
from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.package import preflight_package
from birkin.office.package_types import PackageLimits

_DTD = b"<!DOCTYPE r><r/>"
_ENTITY = b"<!DOCTYPE r [<!ENTITY x 'expanded'>]><r>&x;</r>"
_EXTERNAL = b'<!DOCTYPE r SYSTEM "file:///etc/passwd"><r/>'
_UNBOUND = b"<r><x:item/></r>"
_EXTERNAL_ENTITY = (
    b'<!DOCTYPE r [<!ENTITY x SYSTEM "file:///nonexistent/birkin-xxe">]>'
    b"<r>&x;</r>"
)
_ENCODING_CASES = [
    pytest.param("utf-8", b"", None, id="utf8-no-bom-no-declaration"),
    pytest.param("utf-8", b"\xef\xbb\xbf", "uTf-8", id="utf8-bom-mixed-declaration"),
    pytest.param("utf-16le", b"", None, id="utf16le-no-bom-no-declaration"),
    pytest.param("utf-16le", b"", "uTf-16Le", id="utf16le-no-bom-mixed-declaration"),
    pytest.param("utf-16le", b"\xff\xfe", "UTF-16", id="utf16le-bom-declaration"),
    pytest.param("utf-16be", b"", None, id="utf16be-no-bom-no-declaration"),
    pytest.param("utf-16be", b"", "uTf-16Be", id="utf16be-no-bom-mixed-declaration"),
    pytest.param("utf-16be", b"\xfe\xff", "UTF-16", id="utf16be-bom-declaration"),
]
_PARSE_PART = cast(Callable[[str, bytes], object], vars(xlsx)["_parse_part"])
_PARSE_EXTRACT = cast(
    Callable[[bytes, str], object], vars(extract_package)["_parse"]
)


def _encoded_xml(
    body: str,
    encoding: str,
    bom: bytes,
    declared_encoding: str | None,
) -> bytes:
    declaration = (
        ""
        if declared_encoding is None
        else f"<?xml version='1.0' encoding='{declared_encoding}'?>"
    )
    return bom + f"{declaration}{body}".encode(encoding)


def _assert_typed_error(
    operation: Callable[[], object],
    *,
    stage: str,
    code: DocumentErrorCode = DocumentErrorCode.PACKAGE_INVALID,
) -> DocumentError:
    with pytest.raises(DocumentError) as caught:
        _ = operation()
    assert caught.value.code is code
    assert caught.value.stage == stage
    return caught.value


@pytest.mark.parametrize("xml", [_DTD, _ENTITY, _EXTERNAL, _UNBOUND])
def test_surgery_parser_rejects_unsafe_or_namespace_unbound_xml(xml: bytes) -> None:
    _ = _assert_typed_error(lambda: element_blocks(xml, b"r"), stage="locate")


@pytest.mark.parametrize("xml", [_DTD, _ENTITY, _EXTERNAL, _UNBOUND])
def test_xlsx_parser_rejects_unsafe_or_namespace_unbound_xml(xml: bytes) -> None:
    error = _assert_typed_error(
        lambda: _PARSE_PART("xl/workbook.xml", xml), stage="inspect"
    )
    assert error.details == {"part_uri": "xl/workbook.xml"}


@pytest.mark.parametrize("xml", [_DTD, _ENTITY, _EXTERNAL])
def test_extraction_parser_rejects_dtd_and_entity_features(xml: bytes) -> None:
    error = _assert_typed_error(
        lambda: _PARSE_EXTRACT(xml, "word/document.xml"), stage="import"
    )
    assert error.details == {"part": "word/document.xml"}


def test_extraction_parser_preserves_fragment_namespace_normalization() -> None:
    _ = _PARSE_EXTRACT(_UNBOUND, "word/document.xml")


def _package(path: Path, xml: bytes, name: str = "word/document.xml") -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr(name, xml)
    return path


@pytest.mark.parametrize("xml", [_DTD, _ENTITY, _EXTERNAL])
def test_package_parser_rejects_dtd_and_entity_features(
    tmp_path: Path, xml: bytes
) -> None:
    source = _package(tmp_path / "unsafe.docx", xml)
    error = _assert_typed_error(lambda: preflight_package(source), stage="import")
    assert error.message == "DTD and entities are forbidden"


def test_package_parser_rejects_unbound_namespace_without_synthetic_repair(
    tmp_path: Path,
) -> None:
    source = _package(tmp_path / "unbound.docx", _UNBOUND)
    error = _assert_typed_error(lambda: preflight_package(source), stage="import")
    assert error.message == "malformed XML: word/document.xml"


def test_package_relationship_parser_rejects_unbound_namespace(
    tmp_path: Path,
) -> None:
    source = _package(tmp_path / "unbound.docx", _UNBOUND, "_rels/.rels")
    error = _assert_typed_error(lambda: preflight_package(source), stage="import")
    assert error.message == "malformed relationship XML: _rels/.rels"


def test_package_relationship_parser_rejects_wrong_opc_namespace(
    tmp_path: Path,
) -> None:
    xml = (
        b'<x:Relationships xmlns:x="urn:not-opc">'
        b'<x:Relationship Id="r1" Target="https://example.invalid" '
        b'TargetMode="External"/></x:Relationships>'
    )
    source = _package(tmp_path / "wrong-namespace.docx", xml, "_rels/.rels")

    error = _assert_typed_error(lambda: preflight_package(source), stage="import")

    assert error.message == "malformed relationship XML: _rels/.rels"


@pytest.mark.parametrize(
    ("xml", "limits", "reason"),
    [
        (b"<r><a/><b/></r>", PackageLimits(max_xml_nodes=2), "xml_nodes"),
        (b"<r><a><b/></a></r>", PackageLimits(max_xml_depth=2), "xml_depth"),
        (b'<r a="1" b="2"/>', PackageLimits(max_xml_attributes=1), "xml_attributes"),
        (b"<r>12345</r>", PackageLimits(max_xml_text_bytes=4), "xml_text_bytes"),
    ],
)
def test_package_streaming_parser_preserves_resource_limits(
    tmp_path: Path,
    xml: bytes,
    limits: PackageLimits,
    reason: str,
) -> None:
    source = _package(tmp_path / "limited.docx", xml)
    error = _assert_typed_error(
        lambda: preflight_package(source, limits),
        stage="import",
        code=DocumentErrorCode.LIMIT_EXCEEDED,
    )
    assert error.details == {"reason": reason}


@pytest.mark.parametrize(("encoding", "bom", "declared_encoding"), _ENCODING_CASES)
@pytest.mark.parametrize(
    "declaration",
    ["<!DOCTYPE r>", "<!DOCTYPE r [<!ENTITY x 'bounded'>]>"],
)
def test_safe_xml_rejects_declarations_independent_of_encoding(
    encoding: str,
    bom: bytes,
    declared_encoding: str | None,
    declaration: str,
) -> None:
    from birkin.office.safe_xml import DefusedXmlException, fromstring

    xml = _encoded_xml(
        f"{declaration}<r>&x;</r>" if "ENTITY" in declaration else f"{declaration}<r/>",
        encoding,
        bom,
        declared_encoding,
    )

    with pytest.raises(DefusedXmlException):
        _ = fromstring(xml)


@pytest.mark.parametrize(("encoding", "bom", "declared_encoding"), _ENCODING_CASES)
def test_streaming_xml_parser_rejects_entities_independent_of_encoding(
    encoding: str,
    bom: bytes,
    declared_encoding: str | None,
) -> None:
    from birkin.office.safe_xml import DefusedXmlException, ElementTree

    xml = _encoded_xml(
        "<!DOCTYPE r [<!ENTITY x 'bounded'>]><r>&x;</r>",
        encoding,
        bom,
        declared_encoding,
    )
    parser = ElementTree.XMLParser()

    with pytest.raises(DefusedXmlException):
        parser.feed(xml[:7])
        parser.feed(xml[7:])
        _ = parser.close()


@pytest.mark.parametrize(("encoding", "bom", "declared_encoding"), _ENCODING_CASES)
def test_safe_unicode_office_xml_parses_independent_of_encoding(
    encoding: str,
    bom: bytes,
    declared_encoding: str | None,
) -> None:
    from birkin.office.safe_xml import fromstring

    xml = _encoded_xml(
        '<w:document xmlns:w="urn:office"><w:t>한글 문서</w:t></w:document>',
        encoding,
        bom,
        declared_encoding,
    )

    root = fromstring(xml)

    assert root[0].text == "한글 문서"


def test_safe_xml_security_switches_are_load_bearing() -> None:
    from birkin.office.safe_xml import DefusedXmlException, ElementTree, fromstring

    dtd = fromstring(_DTD, forbid_dtd=False)
    entity = fromstring(
        _ENTITY,
        forbid_dtd=False,
        forbid_entities=False,
    )
    with pytest.raises(DefusedXmlException):
        _ = fromstring(
            _EXTERNAL_ENTITY,
            forbid_dtd=False,
            forbid_entities=False,
            forbid_external=True,
        )
    with pytest.raises(ElementTree.ParseError):
        _ = fromstring(
            _EXTERNAL_ENTITY,
            forbid_dtd=False,
            forbid_entities=False,
            forbid_external=False,
        )

    assert dtd.tag == "r"
    assert entity.text == "expanded"


def test_safe_xml_rejects_utf16_entity_declarations() -> None:
    from birkin.office.safe_xml import DefusedXmlException, ElementTree

    xml = (
        '<?xml version="1.0" encoding="utf-16"?>'
        '<!DOCTYPE r [<!ENTITY x "expanded">]><r>&x;</r>'
    ).encode("utf-16")

    with pytest.raises(DefusedXmlException):
        _ = ElementTree.fromstring(xml)
    with pytest.raises(DefusedXmlException):
        _ = ElementTree.parse(BytesIO(xml))


def test_safe_xml_element_tree_class_rejects_entity_declarations() -> None:
    from birkin.office.safe_xml import DefusedXmlException, ElementTree

    xml = (
        '<?xml version="1.0" encoding="utf-16"?>'
        '<!DOCTYPE r [<!ENTITY x "expanded">]><r>&x;</r>'
    ).encode("utf-16")
    tree = ElementTree.ElementTree()

    with pytest.raises(DefusedXmlException):
        _ = tree.parse(BytesIO(xml))


def test_stdlib_fallback_honors_external_reference_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin.office import safe_xml

    monkeypatch.setattr(safe_xml, "_DefusedXMLParser", None)
    xml = b'<!DOCTYPE r SYSTEM "file:///etc/passwd"><r/>'

    with pytest.raises(safe_xml.DefusedXmlException):
        _ = safe_xml.fromstring(
            xml,
            forbid_dtd=False,
            forbid_entities=False,
            forbid_external=True,
        )


def test_safe_xml_allows_declaration_text_inside_comments() -> None:
    from birkin.office.safe_xml import ElementTree

    root = ElementTree.fromstring(
        b"<r><!-- see <!DOCTYPE html> documentation --></r>"
    )

    assert root.tag == "r"


def test_safe_xml_facade_does_not_expose_unguarded_parser_entrypoints() -> None:
    from birkin.office.safe_xml import ElementTree

    assert not hasattr(ElementTree, "XML")
    assert not hasattr(ElementTree, "XMLID")
    assert not hasattr(ElementTree, "iterparse")


def test_document_service_inspect_rejects_utf16_internal_entity(
    tmp_path: Path,
) -> None:
    from birkin.office.errors import DocumentError
    from birkin.office.service import DocumentService

    document = _encoded_xml(
        "<!DOCTYPE w:document [<!ENTITY x 'bounded'>]>"
        + '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        + 'wordprocessingml/2006/main"><w:p><w:r><w:t>&x;</w:t></w:r></w:p>'
        + "</w:document>",
        "utf-16le",
        b"\xff\xfe",
        "UTF-16",
    )
    source = tmp_path / "hostile.docx"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            b"".join(
                (
                    b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/',
                    b'content-types"><Override PartName="/word/document.xml" ',
                    b'ContentType="application/vnd.openxmlformats-officedocument.',
                    b'wordprocessingml.document.main+xml"/></Types>',
                )
            ),
        )
        archive.writestr("word/document.xml", document)
    artifact = {
        "uri": str(source),
        "content_hash": hashlib.sha256(source.read_bytes()).hexdigest(),
    }

    with pytest.raises(DocumentError) as caught:
        _ = DocumentService(tmp_path).inspect_document(artifact)

    assert caught.value.code is DocumentErrorCode.PACKAGE_INVALID
    assert caught.value.stage == "import"
