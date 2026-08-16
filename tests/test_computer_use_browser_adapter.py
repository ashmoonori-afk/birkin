from __future__ import annotations

import pytest

from birkin.computer_use.backends.base import BackendError
from birkin.computer_use.browser_adapter import (
    BrowserBindingProof,
    validate_browser_route,
)


def _proof(
    *,
    session_id: str = "session-a",
    pid: int = 42,
    process_generation: str = "launch-a",
    native_window_id: str = "window-a",
    window_generation: int = 3,
    mutation_allowed: bool = True,
) -> BrowserBindingProof:
    return BrowserBindingProof(
        session_id=session_id,
        backend_id="native-browser-aside",
        pid=pid,
        process_generation=process_generation,
        native_window_id=native_window_id,
        window_generation=window_generation,
        page_target_id="page-a",
        page_generation=9,
        mutation_allowed=mutation_allowed,
    )


def test_browser_page_route_requires_exact_native_binding() -> None:
    proof = _proof()

    validated = validate_browser_route(
        proof,
        session_id="session-a",
        pid=42,
        process_generation="launch-a",
        native_window_id="window-a",
        window_generation=3,
        mutation=True,
    )

    assert validated is proof


@pytest.mark.parametrize(
    "proof",
    [
        _proof(session_id="session-b"),
        _proof(pid=43),
        _proof(process_generation="launch-b"),
        _proof(native_window_id="window-b"),
        _proof(window_generation=4),
    ],
)
def test_browser_binding_mismatch_fails_closed(
    proof: BrowserBindingProof,
) -> None:
    with pytest.raises(BackendError) as exc_info:
        validate_browser_route(
            proof,
            session_id="session-a",
            pid=42,
            process_generation="launch-a",
            native_window_id="window-a",
            window_generation=3,
            mutation=True,
        )
    assert exc_info.value.code == "identity_mismatch"


def test_browser_mutation_permission_is_explicit() -> None:
    with pytest.raises(BackendError) as exc_info:
        validate_browser_route(
            _proof(mutation_allowed=False),
            session_id="session-a",
            pid=42,
            process_generation="launch-a",
            native_window_id="window-a",
            window_generation=3,
            mutation=True,
        )
    assert exc_info.value.code == "browser_mutation_not_allowed"
