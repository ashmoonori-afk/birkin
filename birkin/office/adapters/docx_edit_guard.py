"""Conservative structural guard for byte-preserving DOCX text edits."""

from __future__ import annotations

import re

from birkin.office.safe_xml import ElementTree
from birkin.office.safe_xml import DefusedXmlException

from ..errors import DocumentError, DocumentErrorCode
from ..xml_tokens import text_tokens
from .docx_fragments import inventory_part

_WORD_NAMESPACES = {
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
    "w",  # retained for conservative refusal of legacy synthetic fixtures
}


def word_edit_context(xml: bytes, target_start: int) -> set[str]:
    """Return semantic Word element names surrounding the exact byte target."""
    opening = re.match(rb"<([A-Za-z_][\w.-]*:)?[A-Za-z_][\w.-]*", xml[target_start:])
    if opening is None:
        raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "locate", "DOCX edit target is malformed")
    marker = b"birkin-edit-target"
    while marker in xml:
        marker += b"-x"
    insertion = target_start + opening.end()
    marked = xml[:insertion] + b' ' + marker + b'="1"' + xml[insertion:]
    try:
        root = ElementTree.fromstring(marked, forbid_dtd=True)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "locate", "DOCX story XML is malformed") from exc
    marker_name = marker.decode("ascii")
    targets = [element for element in root.iter() if element.attrib.get(marker_name) == "1"]
    if len(targets) != 1:
        raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "locate", "DOCX edit target is ambiguous")
    parents = {child: parent for parent in root.iter() for child in parent}
    target = targets[0]
    relevant = list(target.iter())
    current = target
    while current in parents:
        current = parents[current]
        relevant.append(current)
    names: set[str] = set()
    for element in relevant:
        namespace, separator, local_name = element.tag[1:].partition("}")
        if separator and namespace in _WORD_NAMESPACES:
            names.add(local_name)
    return names


def validate_edit_fragment(fragment: bytes) -> None:
    found: list[bytes] = re.findall(rb"(?:</?|\s)([A-Za-z_][\w.-]*):", fragment)
    prefixes = sorted(set(found) - {b"xml", b"xmlns"})
    declarations = b" ".join(
        b'xmlns:' + prefix + b'="urn:' + prefix + b'"' for prefix in prefixes
    )
    inventory = inventory_part(
        "target", b"<root " + declarations + b">" + fragment + b"</root>"
    )
    changes = inventory["tracked_changes"]
    if changes:
        move = any(
            item["type"] in {"moveFrom", "moveTo", "move_from_range", "move_to_range"}
            for item in changes
        )
        reason = "move revisions are unsupported" if move else "nested field or revision boundary"
        raise DocumentError(DocumentErrorCode.UNSUPPORTED_EDIT, "locate", reason)
    tokens = text_tokens(fragment)
    if len(tokens) < 2:
        return
    for records in (inventory["comment_ranges"], inventory["bookmarks"]):
        for item in records:
            boundaries = item.get("boundaries", [])
            crosses = any(
                tokens[0].end < point["offset"] < tokens[-1].start
                for point in boundaries
            )
            if item["state"] == "valid" and crosses:
                raise DocumentError(
                    DocumentErrorCode.UNSUPPORTED_EDIT,
                    "locate",
                    "edit crosses a range boundary",
                )
