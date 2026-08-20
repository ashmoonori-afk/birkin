from __future__ import annotations

from io import BytesIO
import zipfile
from collections.abc import Callable
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
_PARSE_PART = cast(Callable[[str, bytes], object], vars(xlsx)["_parse_part"])
_PARSE_EXTRACT = cast(
    Callable[[bytes, str], object], vars(extract_package)["_parse"]
)


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


def test_streaming_xml_parser_rejects_entity_declarations() -> None:
    from birkin.office.safe_xml import DefusedXmlException, ElementTree

    parser = ElementTree.XMLParser()
    parser.feed(b"<!DOCTYPE r [<!ENTITY x 'expanded'>]>")
    parser.feed(b"<r>&x;</r>")

    with pytest.raises(DefusedXmlException, match="DTD and entity"):
        _ = parser.close()


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
