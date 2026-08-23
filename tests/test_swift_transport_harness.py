from __future__ import annotations

import errno

import pytest

from scripts.native import swift_transport_harness


class _ResetEndpoint:
    def serve_once(self) -> None:
        raise ConnectionResetError(errno.ECONNRESET, "fixture reset")


def test_connection_reset_is_not_counted_as_a_served_connection() -> None:
    with pytest.raises(ConnectionResetError):
        swift_transport_harness.serve_connections(_ResetEndpoint(), count=1)
