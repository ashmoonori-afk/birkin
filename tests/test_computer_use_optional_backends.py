from __future__ import annotations

from birkin.computer_use.backends import BackendSelection, select_backend
from birkin.computer_use.capabilities import DisplayServer


def test_missing_optional_backend_returns_structured_unavailable() -> None:
    selection = select_backend(
        platform="darwin",
        display_server=DisplayServer.QUARTZ,
        available_modules=frozenset(),
    )

    assert selection == BackendSelection(
        backend_id="macos-ax-quartz",
        available=False,
        refusal_code="backend_unavailable",
        missing_dependencies=(
            "AppKit",
            "ApplicationServices",
            "Foundation",
            "Quartz",
        ),
    )


def test_runtime_selection_never_installs_or_prompts() -> None:
    calls: list[str] = []

    selection = select_backend(
        platform="linux",
        display_server=DisplayServer.X11,
        available_modules=frozenset({"Xlib", "pyatspi"}),
        side_effect=lambda operation: calls.append(operation),
    )

    assert selection.available
    assert calls == []
