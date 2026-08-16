from __future__ import annotations

import zipfile
from pathlib import Path


def build_docx_template(path: Path) -> Path:
    entries = {
        "[Content_Types].xml": (
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            b'content-types"><Override PartName="/word/document.xml" '
            b'ContentType="application/vnd.openxmlformats-officedocument.'
            b'wordprocessingml.document.main+xml"/></Types>'
        ),
        "word/document.xml": (
            b'<w:document xmlns:w="http://schemas.openxmlformats.org/'
            b'wordprocessingml/2006/main" '
            b'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml">'
            b'<w:p w14:paraId="P1"><w:sdt><w:sdtPr><w:tag w:val="customer"/>'
            b"</w:sdtPr><w:sdtContent><w:r><w:t>PLACEHOLDER</w:t></w:r>"
            b"</w:sdtContent></w:sdt></w:p><w:tbl/></w:document>"
        ),
        "word/header1.xml": (
            b'<w:hdr xmlns:w="http://schemas.openxmlformats.org/'
            b'wordprocessingml/2006/main"><w:p/></w:hdr>'
        ),
        "word/styles.xml": (
            b'<w:styles xmlns:w="http://schemas.openxmlformats.org/'
            b'wordprocessingml/2006/main"/>'
        ),
        "custom/opaque.xml": b'<x:unknown xmlns:x="urn:opaque" a=" 1 "/>',
    }
    _write_package(path, entries)
    return path


def build_hwpx_template(path: Path) -> Path:
    entries = {
        "mimetype": b"application/hwp+zip",
        "Contents/section0.xml": (
            b'<hp:section xmlns:hp="http://www.hancom.co.kr/hwpml/2011/'
            b'paragraph"><hp:p id="P1"><hp:field id="customer">'
            b"<hp:t>PLACEHOLDER</hp:t></hp:field></hp:p><hp:tbl>"
            b'<hp:tc address="A1"/></hp:tbl><hp:fontRef id="F1"/>'
            b"</hp:section>"
        ),
        "Contents/opaque.xml": b'<x:unknown xmlns:x="urn:opaque" a=" 1 "/>',
    }
    _write_package(path, entries)
    return path


def build_pptx_template(path: Path) -> Path:
    entries = {
        "[Content_Types].xml": (
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            b'content-types"><Override PartName="/ppt/presentation.xml" '
            b'ContentType="application/vnd.openxmlformats-officedocument.'
            b'presentationml.presentation.main+xml"/></Types>'
        ),
        "ppt/presentation.xml": (
            b'<p:presentation xmlns:p="http://schemas.openxmlformats.org/'
            b'presentationml/2006/main"/>'
        ),
        "ppt/slides/slide1.xml": (
            b'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/'
            b'2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/'
            b'2006/main"><p:sp><p:nvPr><p:ph idx="7"/></p:nvPr>'
            b"<a:t>PLACEHOLDER</a:t></p:sp></p:sld>"
        ),
        "ppt/slideMasters/slideMaster1.xml": b'<master id="m1"/>',
        "ppt/slideLayouts/slideLayout1.xml": b'<layout id="l1"/>',
        "ppt/notesSlides/notesSlide1.xml": b"<notes>keep</notes>",
        "ppt/theme/theme1.xml": b"<theme>brand</theme>",
        "ppt/media/logo.bin": b"logo",
        "custom/opaque.xml": b'<x:keep xmlns:x="urn:opaque" a=" 1 "/>',
    }
    _write_package(path, entries)
    return path


def _write_package(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
