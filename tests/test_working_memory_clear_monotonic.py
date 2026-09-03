"""The CLI clear path must not rewind the Working-Memory concurrency token.

``clear_working`` used to write ``empty_working()``, resetting ``revision`` to 0
and reissuing 1, 2, 3 — so an in-flight mutation carrying a stale
``expected_revision`` matched a state it was never computed against.
"""

from __future__ import annotations

import pytest

from birkin import harness


def test_clear_working_keeps_revisions_monotonic():
    session_id = "clear-monotonic"
    _ = harness.update_working(session_id, decisions=["first"])
    _ = harness.update_working(session_id, decisions=["second"])

    assert harness.clear_working(session_id)

    cleared = harness.working_state(session_id)
    assert cleared["revision"] == 3
    assert cleared["decisions"] == []
    assert harness.render_working(session_id) == ""
    assert not harness.clear_working(session_id)

    with pytest.raises(ValueError, match="revision conflict"):
        _ = harness.update_working(
            session_id, decisions=["stale"], expected_revision=2
        )
