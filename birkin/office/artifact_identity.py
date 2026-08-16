"""Extension, magic, and container identity checks for Office artifacts."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from .errors import DocumentError, DocumentErrorCode

_ROOTS = {
    "docx": "word/document.xml",
    "xlsx": "xl/workbook.xml",
    "pptx": "ppt/presentation.xml",
}
_MEDIA = {
    "docx": b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    "xlsx": b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    "pptx": b"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
}
_SUPPORTED = frozenset({*_ROOTS, "hwpx", "pdf", "txt"})
_OPC_CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"


def _mismatch(format_name: str, detail: str) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.PACKAGE_INVALID,
        "probe",
        f".{format_name} extension does not match artifact content: {detail}",
    )


def _read_at(descriptor: int, size: int, offset: int = 0) -> bytes:
    if hasattr(os, "pread"):
        return os.pread(descriptor, size, offset)
    current = os.lseek(descriptor, 0, os.SEEK_CUR)
    try:
        _ = os.lseek(descriptor, offset, os.SEEK_SET)
        return os.read(descriptor, size)
    finally:
        _ = os.lseek(descriptor, current, os.SEEK_SET)


def _zip_identity(descriptor: int, format_name: str) -> None:
    position = os.lseek(descriptor, 0, os.SEEK_CUR)
    stream = os.fdopen(os.dup(descriptor), "rb")
    try:
        with zipfile.ZipFile(stream) as archive:
            names = set(archive.namelist())
            if format_name == "hwpx":
                if "mimetype" not in names or archive.read("mimetype") != b"application/hwp+zip":
                    raise _mismatch(format_name, "HWPX mimetype is absent or invalid")
                if not any(name.startswith("Contents/") and name.endswith(".xml") for name in names):
                    raise _mismatch(format_name, "HWPX content parts are absent")
                return
            root = _ROOTS[format_name]
            other_roots = set(_ROOTS.values()) - {root}
            if root not in names or names.intersection(other_roots):
                raise _mismatch(format_name, "package main part identifies another format")
            if "[Content_Types].xml" not in names:
                raise _mismatch(format_name, "OOXML content type manifest is absent")
            manifest = archive.read("[Content_Types].xml")
            try:
                types = ElementTree.fromstring(manifest, forbid_dtd=True)
            except (ElementTree.ParseError, DefusedXmlException) as exc:
                raise _mismatch(format_name, "OOXML content type manifest is malformed") from exc
            if types.tag != f"{{{_OPC_CONTENT_TYPES}}}Types":
                raise _mismatch(format_name, "OOXML content type manifest is malformed")
            declarations = [
                item
                for item in types
                if item.tag == f"{{{_OPC_CONTENT_TYPES}}}Override"
                and item.attrib.get("PartName") == f"/{root}"
            ]
            expected = _MEDIA[format_name].decode("ascii")
            if len(declarations) != 1 or declarations[0].attrib.get("ContentType") != expected:
                raise _mismatch(format_name, "OOXML main-part manifest disagrees")
    except DocumentError:
        raise
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
        raise _mismatch(format_name, "invalid ZIP package") from exc
    finally:
        stream.close()
        _ = os.lseek(descriptor, position, os.SEEK_SET)


def verify_descriptor_identity(descriptor: int, path: Path) -> str:
    format_name = path.suffix.lower().lstrip(".")
    if format_name not in _SUPPORTED:
        raise DocumentError(DocumentErrorCode.UNSUPPORTED_FORMAT, "probe", f"unsupported artifact extension: {format_name or '(none)'}")
    size = os.fstat(descriptor).st_size
    prefix = _read_at(descriptor, min(size, 8))
    if format_name == "pdf":
        tail = _read_at(descriptor, min(size, 1024), max(0, size - 1024))
        if not prefix.startswith(b"%PDF-") or b"%%EOF" not in tail:
            raise _mismatch(format_name, "PDF signature or end marker is absent")
    elif format_name == "txt":
        payload = _read_at(descriptor, size)
        try:
            _ = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _mismatch(format_name, "text is not UTF-8") from exc
        if b"\x00" in payload:
            raise _mismatch(format_name, "text contains NUL bytes")
    else:
        if not prefix.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
            raise _mismatch(format_name, "ZIP magic is absent")
        _zip_identity(descriptor, format_name)
    return format_name
