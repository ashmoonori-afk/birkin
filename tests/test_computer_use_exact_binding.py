from __future__ import annotations

import pytest

from birkin.computer_use.bindings import BindingError, BindingStore
from birkin.computer_use.models import ElementTarget


def test_element_target_requires_matching_app_window_and_snapshot() -> None:
    store = BindingStore(session_id="session-a", backend_id="fake")
    app_ref = store.bind_app(
        pid=100,
        process_generation="launch-a",
        native_identity="org.birkin.QAFixture",
    )
    other_app_ref = store.bind_app(
        pid=101,
        process_generation="launch-b",
        native_identity="org.birkin.QASentinel",
    )
    window_ref = store.bind_window(
        app_ref=app_ref,
        native_window_id="window-1",
        window_generation=4,
    )
    snapshot = store.begin_snapshot(
        app_ref=app_ref,
        window_ref=window_ref,
        mode="ax",
        ui_fingerprint="state-a",
    )
    element_ref = store.bind_element(
        snapshot_ref=snapshot.token,
        accessibility_identity="AXTextField:value",
        accessibility_path=("AXWindow:0", "AXTextField:0"),
    )

    target = ElementTarget(
        app_ref=other_app_ref,
        window_ref=window_ref,
        snapshot_ref=snapshot.token,
        element_ref=element_ref,
    )
    with pytest.raises(BindingError) as exc_info:
        store.resolve_element(target)
    assert exc_info.value.code == "identity_mismatch"


def test_process_generation_change_invalidates_window_and_elements() -> None:
    store = BindingStore(session_id="session-a", backend_id="fake")
    app_ref = store.bind_app(
        pid=100,
        process_generation="launch-a",
        native_identity="org.birkin.QAFixture",
    )
    window_ref = store.bind_window(
        app_ref=app_ref,
        native_window_id="window-1",
        window_generation=1,
    )
    snapshot = store.begin_snapshot(
        app_ref=app_ref,
        window_ref=window_ref,
        mode="ax",
        ui_fingerprint="state-a",
    )
    element_ref = store.bind_element(
        snapshot_ref=snapshot.token,
        accessibility_identity="AXButton:save",
        accessibility_path=("AXWindow:0", "AXButton:1"),
    )
    target = ElementTarget(
        app_ref=app_ref,
        window_ref=window_ref,
        snapshot_ref=snapshot.token,
        element_ref=element_ref,
    )

    store.observe_process_generation(pid=100, process_generation="launch-b")

    with pytest.raises(BindingError) as exc_info:
        store.resolve_element(target)
    assert exc_info.value.code == "stale_ref"
