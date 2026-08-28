"""Durable HMAC authority and retention window for export receipts."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

from birkin.private_storage import (
    create_private_temp,
    open_private_file_for_read,
    publish_private_temp,
)

from .errors import DocumentError, DocumentErrorCode

RETENTION_DAYS = 30
_KEY_NAME = "receipt_hmac_key"


def _error(
    message: str,
    *,
    denied: bool = False,
    retryable: bool = False,
) -> DocumentError:
    return DocumentError(
        (
            DocumentErrorCode.PERMISSION_DENIED
            if denied
            else DocumentErrorCode.PRECONDITION_FAILED
        ),
        "export_receipt",
        message,
        retryable=retryable,
    )


def receipt_window(
    now: datetime | None = None,
) -> tuple[str, str]:
    issued = now or datetime.now(timezone.utc)
    if issued.tzinfo is None:
        raise ValueError("receipt time must include a timezone")
    issued = issued.astimezone(timezone.utc)
    expires = issued + timedelta(days=RETENTION_DAYS)
    return _timestamp(issued), _timestamp(expires)


def sign_receipt(value: Mapping[str, object], office_home: Path) -> str:
    try:
        key = _load_or_create_key(office_home)
    except OSError as exc:
        raise _error(
            "export receipt authentication key is unavailable",
            retryable=True,
        ) from exc
    return _signature(value, key)


def authenticate_receipt(
    value: Mapping[str, object],
    office_home: Path,
    *,
    now: datetime | None = None,
) -> bool:
    signature = value.get("receipt_hmac")
    if signature is None:
        return False
    issued, expires = verified_receipt_window(value, office_home)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise _error("export receipt current time is invalid", denied=True)
    current = current.astimezone(timezone.utc)
    if current < issued or current >= expires:
        raise _error("export receipt retention window expired", denied=True)
    return True


def verified_receipt_window(
    value: Mapping[str, object],
    office_home: Path,
) -> tuple[datetime, datetime]:
    signature = value.get("receipt_hmac")
    if not isinstance(signature, str) or len(signature) != 64:
        raise _error("export receipt authentication is invalid", denied=True)
    expected = _signature(
        {key: item for key, item in value.items() if key != "receipt_hmac"},
        _load_existing_key(office_home),
    )
    if not hmac.compare_digest(signature, expected):
        raise _error("export receipt authentication mismatch", denied=True)
    issued = _parse_timestamp(value.get("issued_at"))
    expires = _parse_timestamp(value.get("expires_at"))
    if (
        expires <= issued
        or expires - issued > timedelta(days=RETENTION_DAYS)
    ):
        raise _error("export receipt retention window is invalid", denied=True)
    return issued, expires


def _canonical(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise _error("export receipt cannot be authenticated") from exc


def _signature(value: Mapping[str, object], key: bytes) -> str:
    return hmac.new(
        key,
        _canonical(value),
        hashlib.sha256,
    ).hexdigest()


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise _error("export receipt retention timestamp is invalid", denied=True)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise _error(
            "export receipt retention timestamp is invalid",
            denied=True,
        ) from exc
    return parsed.astimezone(timezone.utc)


def _read_key(path: Path) -> bytes:
    descriptor = open_private_file_for_read(path)
    try:
        payload = os.read(descriptor, 65)
    finally:
        os.close(descriptor)
    try:
        key = bytes.fromhex(payload.decode("ascii").strip())
    except (UnicodeDecodeError, ValueError) as exc:
        raise _error("export receipt authentication key is malformed") from exc
    if len(key) != 32 or len(payload) > 64:
        raise _error("export receipt authentication key is malformed")
    return key


def _load_or_create_key(office_home: Path) -> bytes:
    path = office_home / _KEY_NAME
    try:
        return _read_key(path)
    except FileNotFoundError:
        pass
    descriptor, temporary_name = create_private_temp(
        office_home,
        prefix=f".{_KEY_NAME}.",
    )
    temporary = Path(temporary_name)
    key = secrets.token_bytes(32)
    try:
        try:
            payload = key.hex().encode("ascii")
            remaining = memoryview(payload)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("receipt key write made no progress")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if not publish_private_temp(temporary, path):
            return _read_key(path)
        return key
    finally:
        temporary.unlink(missing_ok=True)


def _load_existing_key(office_home: Path) -> bytes:
    try:
        return _read_key(office_home / _KEY_NAME)
    except OSError as exc:
        raise _error(
            "export receipt authentication key is unavailable",
            retryable=True,
        ) from exc
