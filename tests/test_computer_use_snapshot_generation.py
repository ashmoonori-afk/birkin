from __future__ import annotations

import pytest

from birkin.computer_use.bindings import BindingError, BindingStore
from birkin.computer_use.models import ElementTarget


def _captured_button(
    store: BindingStore,
    *,
    fingerprint: str,
) -> tuple[str, ElementTarget]:
    app_ref = store.bind_app(
        pid=420,
        process_generation="launch-1",
        native_identity="org.birkin.QAFixture",
    )
    window_ref = store.bind_window(
        app_ref=app_ref,
        native_window_id="99",
        window_generation=1,
    )
    snapshot = store.begin_snapshot(
        app_ref=app_ref,
        window_ref=window_ref,
        mode="ax",
        ui_fingerprint=fingerprint,
    )
    element_ref = store.bind_element(
        snapshot_ref=snapshot.token,
        accessibility_identity="AXButton:counter",
        accessibility_path=("AXWindow:0", "AXButton:0"),
    )
    target = ElementTarget(
        app_ref=app_ref,
        window_ref=window_ref,
        snapshot_ref=snapshot.token,
        element_ref=element_ref,
    )
    return element_ref, target


def test_new_capture_increments_generation_and_stales_prior_refs() -> None:
    store = BindingStore(session_id="session-a", backend_id="fake")
    _, old_target = _captured_button(store, fingerprint="ui-v1")

    second = store.begin_snapshot(
        app_ref=old_target.app_ref,
        window_ref=old_target.window_ref,
        mode="ax",
        ui_fingerprint="ui-v2",
    )

    assert second.snapshot_generation == 2
    with pytest.raises(BindingError) as exc_info:
        store.resolve_element(old_target)
    assert exc_info.value.code == "stale_ref"


def test_current_opaque_ref_resolves_only_in_issuing_session() -> None:
    first = BindingStore(session_id="session-a", backend_id="fake")
    element_ref, target = _captured_button(first, fingerprint="ui-v1")
    second = BindingStore(session_id="session-b", backend_id="fake")

    assert element_ref not in repr(first.element_binding(element_ref))
    assert first.resolve_element(target).accessibility_identity == ("AXButton:counter")
    with pytest.raises(BindingError) as exc_info:
        second.resolve_element(target)
    assert exc_info.value.code == "cross_session_ref"
