from __future__ import annotations
import hashlib
from dataclasses import dataclass
from pathlib import Path
from .errors import DocumentError, DocumentErrorCode
from .package import clone_package, preflight_package
from .xml_splice import splice_text

@dataclass(frozen=True)
class PatchOperation:
    part_uri: str
    locator: dict[str, object]
    value: str
    expected_revision_hash: str

def apply_patch(source: Path, output: Path, operations: list[PatchOperation], *, expected_source_sha256: str) -> str:
    source = Path(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != expected_source_sha256:
        raise DocumentError(DocumentErrorCode.SOURCE_CHANGED, 'apply', 'source hash changed', artifact_sha256=digest)
    for op in operations:
        if op.expected_revision_hash != digest:
            raise DocumentError(DocumentErrorCode.PRECONDITION_FAILED, 'plan', 'stale operation revision')
    manifest = preflight_package(source)
    replacements: dict[str, bytes] = {}
    for op in operations:
        current = replacements.get(op.part_uri)
        if current is None:
            part = manifest['parts'].get(op.part_uri)
            current = part['bytes'] if part is not None else None
        if current is None:
            raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND, 'locate', 'part not found')
        replacements[op.part_uri] = splice_text(current, op.locator, op.value)
    _ = clone_package(source, output, replacements)
    return hashlib.sha256(Path(output).read_bytes()).hexdigest()
