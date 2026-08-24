from __future__ import annotations

from dataclasses import replace

from birkin.workspace.contracts import WorkspaceCommand, object_mapping
from birkin.workspace.records import CommandReceipt
from scripts.native.native_vector_catalogue import build_vectors


def test_command_vector_parses_when_built_from_catalogue() -> None:
    # Given
    vector = dict(build_vectors())["command"]
    body = object_mapping(vector["body"], "command vector body")

    # When
    command = WorkspaceCommand.parse(body["command"])

    # Then
    assert command.client_context.to_json() == {
        "surface": "windows",
        "view_id": "conversation",
    }
    assert command.payload == {"session_id": "s-1"}


def test_every_receipt_vector_matches_current_public_model() -> None:
    # Given
    receipt = CommandReceipt(
        protocol_version=1,
        command_id="cmd-1",
        session_id="session-1",
        actor_id="windows:conversation",
        accepted_cursor=43,
        state="completed",
        result_event_cursor=44,
        fingerprint="fixture-fingerprint",
    )
    expected_receipts = (
        ("receipt", receipt),
        ("bounded_identifiers", replace(receipt, command_id="a.b:c-d_e")),
    )
    expected_bodies = {
        name: expected.to_public_json() for name, expected in expected_receipts
    }
    for body in expected_bodies.values():
        body["outcome"] = "accepted"

    # When
    receipt_vectors = {
        name: object_mapping(vector["body"], f"{name} receipt vector body")
        for name, vector in build_vectors()
        if vector["kind"] == "receipt"
    }

    # Then
    assert receipt_vectors == expected_bodies
