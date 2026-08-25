"""Bounded Office projection coverage for the native frame surface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from birkin.native.product_surface_authorities import OfficeSurfaceAuthority
from birkin.native.protocol import (
    MAX_FRAME_BYTES,
    NATIVE_PROTOCOL_NAME,
    NATIVE_PROTOCOL_VERSION,
    JSONValue,
    NativeEnvelope,
    encode_frame,
)
from birkin.office.service import DocumentService
from tests.native_office_support import approved_docx

_OFFICE_SNAPSHOT_ENTRY_LIMIT = 8
_COMMAND_PAYLOAD_BYTES = 65_536


def _object(value: JSONValue) -> dict[str, JSONValue]:
    assert isinstance(value, dict)
    return cast(dict[str, JSONValue], value)


def _objects(value: JSONValue) -> list[dict[str, JSONValue]]:
    assert isinstance(value, list)
    return [_object(item) for item in cast(list[JSONValue], value)]


def _surface_frame(payload: dict[str, JSONValue]) -> bytes:
    return encode_frame(NativeEnvelope.parse({
        "protocol": NATIVE_PROTOCOL_NAME,
        "protocol_version": NATIVE_PROTOCOL_VERSION,
        "kind": "surface_snapshot",
        "id": "office-bounded-snapshot",
        "in_reply_to": None,
        "body": {
            "surface": "office",
            "revision": 1,
            "payload": payload,
        },
    }))


def test_office_snapshot_is_bounded_when_create_and_open_exceed_the_entry_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given repeated Office operations, When their count exceeds the limit,
    Then the projection retains the newest entries and fits one native frame.
    """
    # Given
    authority = OfficeSurfaceAuthority(DocumentService(tmp_path / "office"))
    monkeypatch.setenv("BIRKIN_HOME", str(authority.service.home.parent))

    # When
    artifacts = [
        _object(cast(JSONValue, approved_docx(authority.service.home, index)))
        for index in range(_OFFICE_SNAPSHOT_ENTRY_LIMIT + 1)
    ]
    for artifact in artifacts:
        _ = authority.open({"artifact": artifact})

    # Then
    payload = authority.snapshot()
    documents = _objects(cast(JSONValue, payload["documents"]))
    receipts = _objects(cast(JSONValue, payload["receipts"]))
    diffs = _objects(cast(JSONValue, payload["diffs"]))
    assert set(payload) == {
        "inventory", "form", "selected_artifact_id", "documents", "receipts", "diffs", "refusal",
    }
    assert diffs == []
    assert [item["artifact_id"] for item in documents] == [
        item["artifact_id"] for item in artifacts[1:]
    ]
    assert [item["operation"] for item in receipts] == ["document_open"] * _OFFICE_SNAPSHOT_ENTRY_LIMIT
    assert len(_surface_frame(cast(dict[str, JSONValue], payload))) - 4 <= MAX_FRAME_BYTES


def test_office_snapshot_discards_unknown_open_artifact_fields_within_frame_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given command-sized artifact aliases, When eight documents are opened,
    Then only verified artifact fields are retained within one native frame.
    """
    # Given
    authority = OfficeSurfaceAuthority(DocumentService(tmp_path / "office"))
    monkeypatch.setenv("BIRKIN_HOME", str(authority.service.home.parent))
    artifacts = [
        _object(cast(JSONValue, approved_docx(authority.service.home, index)))
        for index in range(_OFFICE_SNAPSHOT_ENTRY_LIMIT)
    ]

    # When
    for artifact in artifacts:
        supplied = {**artifact, "padding_alias": "x" * 50_000}
        assert len(json.dumps({"artifact": supplied}, separators=(",", ":")).encode()) <= _COMMAND_PAYLOAD_BYTES
        _ = authority.open({"artifact": supplied})

    # Then
    payload = authority.snapshot()
    documents = _objects(cast(JSONValue, payload["documents"]))
    assert len(documents) == _OFFICE_SNAPSHOT_ENTRY_LIMIT
    assert len(_surface_frame(cast(dict[str, JSONValue], payload))) - 4 <= MAX_FRAME_BYTES
    assert all(set(document) == {
        "artifact_id",
        "content_hash",
        "media_type",
        "uri",
        "sensitivity",
        "acl_fingerprint",
        "provenance",
        "conversion",
        "active_content",
    } for document in documents)
    assert all("padding_alias" not in document for document in documents)
