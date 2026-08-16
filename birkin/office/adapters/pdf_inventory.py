"""Bounded, inert traversal of parsed PDF objects."""

from __future__ import annotations

from collections.abc import Iterator
from itertools import pairwise

from ..errors import DocumentError, DocumentErrorCode
from .pdf_types import (
    ParsedPage,
    ParsedPdf,
    PdfArray,
    PdfIndirect,
    PdfMapping,
    array_items,
    mapping,
    resolve,
)


def _walk(value: object, path: str = "catalog") -> Iterator[tuple[str, object]]:
    pending: list[tuple[str, object]] = [(path, value)]
    seen: set[tuple[object, ...]] = set()
    count = 0
    while pending:
        current_path, raw = pending.pop()
        key = (
            ("indirect", raw.idnum, raw.generation)
            if isinstance(raw, PdfIndirect)
            else ("direct", id(raw))
        )
        if key in seen:
            continue
        seen.add(key)
        current = resolve(raw)
        count += 1
        if count > 10_000:
            raise DocumentError(
                DocumentErrorCode.LIMIT_EXCEEDED,
                "inspect",
                "PDF object inventory limit exceeded",
                details={"reason": "pdf_object_limit"},
            )
        yield current_path, current
        current_mapping = mapping(current)
        if current_mapping is not None:
            for name, child in reversed(list(current_mapping.items())):
                if str(name) != "/Parent":
                    pending.append((f"{current_path}.{name}", child))
        elif isinstance(current, PdfArray) and not isinstance(
            current, (str, bytes, bytearray)
        ):
            for index in range(len(current) - 1, -1, -1):
                pending.append((f"{current_path}[{index}]", current[index]))


def field_count(acroform: object) -> int:
    form = mapping(acroform)
    empty: tuple[object, ...] = ()
    fields = form.get("/Fields", empty) if form is not None else empty
    return sum(
        "/FT" in item_mapping or "/T" in item_mapping
        for _, item in _walk(fields, "AcroForm.Fields")
        if (item_mapping := mapping(item)) is not None
    )


def images_on_page(page: ParsedPage) -> int:
    resources = mapping(page.get("/Resources", {}))
    xobjects = mapping(resources.get("/XObject", {})) if resources is not None else None
    if xobjects is None:
        return 0
    count = 0
    for item in xobjects.values():
        image = mapping(item)
        if image is not None and str(image.get("/Subtype")) == "/Image":
            count += 1
    return count


def _byte_range(value: object, size: int) -> tuple[list[int] | None, str]:
    raw_values = list(array_items(value))
    if not raw_values or not all(isinstance(item, int) for item in raw_values):
        return None, "invalid"
    values = [item for item in raw_values if isinstance(item, int)]
    if len(values) < 4 or len(values) % 2 or any(item < 0 for item in values):
        return values, "invalid"
    segments = list(zip(values[::2], values[1::2]))
    if any(offset + length > size for offset, length in segments):
        return values, "invalid"
    if any(left[0] + left[1] > right[0] for left, right in pairwise(segments)):
        return values, "invalid"
    reaches_boundaries = (
        segments[0][0] == 0 and segments[-1][0] + segments[-1][1] == size
    )
    coverage = "file_boundaries_with_exclusions" if reaches_boundaries else "partial"
    return values, coverage


def _signature(item: PdfMapping, path: str, size: int) -> dict[str, object]:
    byte_range, coverage = _byte_range(item.get("/ByteRange"), size)
    contents = resolve(item.get("/Contents"))
    if isinstance(contents, str):
        contents_size = len(contents.encode("latin-1", errors="replace"))
    elif isinstance(contents, bytes):
        contents_size = len(contents)
    else:
        contents_size = 0
    references = item.get("/Reference", [])
    doc_mdp = False
    permission: int | None = None
    for _, reference in _walk(references, f"{path}.Reference"):
        reference_mapping = mapping(reference)
        if (
            reference_mapping is not None
            and str(reference_mapping.get("/TransformMethod")) == "/DocMDP"
        ):
            doc_mdp = True
            parameters = mapping(reference_mapping.get("/TransformParams", {}))
            raw_permission = parameters.get("/P") if parameters is not None else None
            permission = raw_permission if isinstance(raw_permission, int) else None
    return {
        "object_path": path,
        "contents_present": "/Contents" in item,
        "signature_bytes_present": contents_size > 0,
        "signature_bytes_length": contents_size,
        "byte_range": byte_range,
        "byte_range_coverage": coverage,
        "byte_range_valid": coverage != "invalid",
        "byte_range_starts_at_zero": bool(byte_range and byte_range[0] == 0),
        "byte_range_ends_at_eof": bool(
            byte_range and byte_range[-2] + byte_range[-1] == size
        ),
        "doc_mdp": doc_mdp,
        "doc_mdp_permission": permission,
        "cryptographic_verification": "unsupported",
        "trust_evaluation": "unsupported",
    }


def inventory(
    reader: ParsedPdf, size: int
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    signatures: list[dict[str, object]] = []
    active: list[dict[str, object]] = []
    seen_findings: set[tuple[str, str]] = set()
    action_names = {
        "/JavaScript",
        "/Launch",
        "/URI",
        "/GoToR",
        "/SubmitForm",
        "/ImportData",
    }
    for path, raw_item in _walk(reader.root_object):
        item = mapping(raw_item)
        if item is None:
            continue
        if str(item.get("/Type")) == "/Sig" or "/ByteRange" in item:
            signatures.append(_signature(item, path, size))
        action = str(item.get("/S"))
        findings: list[tuple[str, str]] = []
        if action in action_names:
            findings.append((action.removeprefix("/"), "action"))
        for key, kind in (
            ("/OpenAction", "open_action"),
            ("/AA", "additional_actions"),
            ("/JavaScript", "javascript_name_tree"),
            ("/EmbeddedFiles", "embedded_files"),
            ("/EF", "embedded_file"),
        ):
            if key in item:
                findings.append((kind, "catalog_or_object_entry"))
        for kind, source in findings:
            identity = (kind, path)
            if identity not in seen_findings:
                seen_findings.add(identity)
                active.append(
                    {
                        "kind": kind,
                        "source": source,
                        "object_path": path,
                        "executed": False,
                    }
                )
    return signatures, active
