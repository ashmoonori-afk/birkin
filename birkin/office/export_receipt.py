"""Parse durable public export receipts into rollback authority."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypeGuard

from .errors import DocumentError, DocumentErrorCode
from .export_policy import JSONValue, ExportReceipt


def _denied(message: str) -> DocumentError:
    return DocumentError(DocumentErrorCode.PERMISSION_DENIED, "rollback", message)


def _is_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _is_mapping(value: object) -> TypeGuard[Mapping[object, object]]:
    return isinstance(value, Mapping)


def _json_value(value: object) -> JSONValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if _is_list(value):
        return [_json_value(item) for item in value]
    if _is_mapping(value):
        return _operation(value)
    raise _denied("export receipt operation values are invalid")


def _operation(value: Mapping[object, object]) -> dict[str, JSONValue]:
    parsed: dict[str, JSONValue] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise _denied("export receipt operation keys are invalid")
        parsed[key] = _json_value(item)
    return parsed


def _required_text(value: object, message: str) -> str:
    if not isinstance(value, str) or not value:
        raise _denied(message)
    return value


def restore_export_receipt(
    value: Mapping[str, object],
    backup_root: Path,
    resolve_destination: Callable[[Path], Path],
) -> ExportReceipt:
    """Restore private rollback state from one durable public receipt."""
    token = value.get("rollback_token")
    destination = value.get("path")
    source_sha256 = value.get("source_sha256")
    output_sha256 = value.get("output_sha256")
    actor = value.get("actor")
    proposal_digest = value.get("proposal_digest")
    existed = value.get("destination_existed")
    destination_sha256 = value.get("destination_sha256")
    operations = value.get("operations")
    try:
        token_valid = isinstance(token, str) and uuid.UUID(token).hex == token
    except ValueError:
        token_valid = False
    if not token_valid or not isinstance(destination, str):
        raise _denied("export receipt identity is invalid")
    source_sha256 = _required_text(source_sha256, "export receipt proof is invalid")
    output_sha256 = _required_text(output_sha256, "export receipt proof is invalid")
    actor = _required_text(actor, "export receipt proof is invalid")
    proposal_digest = _required_text(
        proposal_digest, "export receipt proof is invalid"
    )
    if not isinstance(existed, bool) or (
        destination_sha256 is not None and not isinstance(destination_sha256, str)
    ):
        raise _denied("export receipt destination state is invalid")
    if not _is_list(operations):
        raise _denied("export receipt operations are invalid")
    parsed_operations: list[dict[str, JSONValue]] = []
    for operation in operations:
        if not _is_mapping(operation):
            raise _denied("export receipt operations are invalid")
        parsed_operations.append(_operation(operation))
    return ExportReceipt(
        rollback_token=_required_text(token, "export receipt identity is invalid"),
        destination=resolve_destination(Path(destination)),
        source_sha256=source_sha256,
        output_sha256=output_sha256,
        operations=tuple(parsed_operations),
        actor=actor,
        proposal_digest=proposal_digest,
        destination_existed=existed,
        destination_sha256=destination_sha256,
        backup=backup_root / f"{token}.bak" if existed else None,
    )
