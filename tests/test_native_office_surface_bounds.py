"""Bounded Office projection coverage for the native frame surface."""

from __future__ import annotations

from pathlib import Path
from typing import cast

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

_OFFICE_SNAPSHOT_ENTRY_LIMIT = 8


def _object(value: JSONValue) -> dict[str, JSONValue]:
    assert isinstance(value, dict)
    return cast(dict[str, JSONValue], value)


def _objects(value: JSONValue) -> list[dict[str, JSONValue]]:
    assert isinstance(value, list)
    return [_object(item) for item in cast(list[JSONValue], value)]


def test_office_snapshot_is_bounded_when_create_and_open_exceed_the_entry_limit(
    tmp_path: Path,
) -> None:
    """Given repeated Office operations, When their count exceeds the limit,
    Then the projection retains the newest entries and fits one native frame.
    """
    # Given
    authority = OfficeSurfaceAuthority(DocumentService(tmp_path / "office"))
    artifacts: list[dict[str, JSONValue]] = []

    # When
    for index in range(_OFFICE_SNAPSHOT_ENTRY_LIMIT + 1):
        created = authority.create({
            "format": "docx",
            "content": {"paragraphs": [f"bounded document {index}"]},
            "output_name": f"bounded-{index}.docx",
        })
        artifacts.append(_object(cast(JSONValue, created["document"])))
    for artifact in artifacts:
        _ = authority.open({"artifact": artifact})

    # Then
    payload = authority.snapshot()
    documents = _objects(cast(JSONValue, payload["documents"]))
    receipts = _objects(cast(JSONValue, payload["receipts"]))
    assert set(payload) == {"inventory", "documents", "receipts", "refusal"}
    assert [item["artifact_id"] for item in documents] == [
        item["artifact_id"] for item in artifacts[1:]
    ]
    assert [item["operation"] for item in receipts] == ["document_open"] * _OFFICE_SNAPSHOT_ENTRY_LIMIT
    frame = encode_frame(NativeEnvelope.parse({
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
    assert len(frame) - 4 <= MAX_FRAME_BYTES
