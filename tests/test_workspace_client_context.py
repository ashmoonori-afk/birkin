from __future__ import annotations

import pytest

from birkin.workspace.contracts import ClientContext, ProtocolError


def test_windows_client_context_round_trips_when_parsed() -> None:
    # Given
    raw = {"surface": "windows", "view_id": "conversation"}

    # When
    context = ClientContext.parse(raw)

    # Then
    assert context.to_json() == raw


def test_unknown_client_surface_is_rejected_when_parsed() -> None:
    # Given
    raw = {"surface": "unadvertised", "view_id": "conversation"}

    # When / Then
    with pytest.raises(ProtocolError):
        _ = ClientContext.parse(raw)
