"""Socket budget for suites that drive an in-process HTTP server.

These tests bind an ``HTTPServer`` on loopback inside the test process, so the
client never waits on a network — only on the interpreter scheduling the server
thread. A loaded CI runner (Windows especially) can starve that thread for
several seconds, which is a slow host rather than a hung server, and a 2-4s
socket budget turns it into a spurious ``TimeoutError``.
``BIRKIN_TEST_HTTP_TIMEOUT`` retunes the budget per machine. Raising the bound
never weakens an assertion — a response that never arrives still fails, only
later.
"""

from __future__ import annotations

import os

_DEFAULT_TIMEOUT = 30.0
_MAX_TIMEOUT = 300.0


def local_http_timeout() -> float:
    """Seconds one loopback HTTP exchange in the suite may take."""
    raw = os.environ.get("BIRKIN_TEST_HTTP_TIMEOUT")
    if raw is None:
        return _DEFAULT_TIMEOUT
    try:
        seconds = float(raw)
    except ValueError:
        return _DEFAULT_TIMEOUT
    if not seconds > 0:  # rejects zero, negatives, and NaN
        return _DEFAULT_TIMEOUT
    return min(seconds, _MAX_TIMEOUT)
