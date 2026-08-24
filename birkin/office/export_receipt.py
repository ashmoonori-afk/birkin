"""Parse durable public export receipts into rollback authority."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from .errors import DocumentError, DocumentErrorCode
from .export_policy import JSONValue, ExportReceipt


def _denied(message: str) -> DocumentError:
    return DocumentError(DocumentErrorCode.PERMISSION_DENIED, "rollback", message)


def _json_value(value: object) -> JSONValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        parsed: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _denied("export receipt operation keys are invalid")
            parsed[key] = _json_value(item)
        return parsed
    raise _denied("export receipt operation values are invalid")


def _operation(value: Mapping[object, object]) -> dict[str, JSONValue]:
    parsed: dict[str, JSONValue] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise _denied("export receipt operation keys are invalid")
        parsed[key] = _json_value(item)
    return parsed


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
    if not all(
        isinstance(item, str) and item
        for item in (source_sha256, output_sha256, actor, proposal_digest)
    ):
        raise _denied("export receipt proof is invalid")
    if not isinstance(existed, bool) or (
        destination_sha256 is not None and not isinstance(destination_sha256, str)
    ):
        raise _denied("export receipt destination state is invalid")
    if not isinstance(operations, list) or not all(
        isinstance(operation, Mapping) for operation in operations
    ):
        raise _denied("export receipt operations are invalid")
    return ExportReceipt(
        rollback_token=token,
        destination=resolve_destination(Path(destination)),
        source_sha256=source_sha256,
        output_sha256=output_sha256,
        operations=tuple(_operation(operation) for operation in operations),
        actor=actor,
        proposal_digest=proposal_digest,
        destination_existed=existed,
        destination_sha256=destination_sha256,
        backup=backup_root / f"{token}.bak" if existed else None,
    )
