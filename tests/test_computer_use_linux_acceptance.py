from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest

from birkin.computer_use.models import ObservedApp
from scripts.qa import computer_use_linux_acceptance as acceptance


class _Backend:
    def __init__(self, *, visible: bool) -> None:
        self.visible = visible
        self.calls = 0

    def list_apps(self) -> tuple[ObservedApp, ...]:
        self.calls += 1
        if not self.visible:
            return ()
        return (
            ObservedApp(
                pid=42,
                process_generation="42:1",
                native_identity="/fixture",
                name="fixture",
            ),
        )


class _Root:
    def __init__(self) -> None:
        self.event_mask: int | None = None

    def change_attributes(self, *, event_mask: int) -> None:
        self.event_mask = event_mask


class _Display:
    def __init__(self, event: SimpleNamespace) -> None:
        self.root = _Root()
        self._events = [event]
        self.flushed = False
        self.closed = False

    def screen(self) -> SimpleNamespace:
        return SimpleNamespace(root=self.root)

    def intern_atom(self, name: str) -> int:
        assert name == "_NET_CLIENT_LIST"
        return 99

    def fileno(self) -> int:
        return 7

    def flush(self) -> None:
        self.flushed = True

    def pending_events(self) -> int:
        return len(self._events)

    def next_event(self) -> SimpleNamespace:
        return self._events.pop(0)

    def close(self) -> None:
        self.closed = True


class _Selector:
    def __init__(self, on_select: Callable[[], None]) -> None:
        self._on_select = on_select
        self.registered: object | None = None
        self.selected = False
        self.closed = False

    def register(self, fileobj: object, _events: int) -> None:
        self.registered = fileobj

    def select(self, _timeout: float) -> list[tuple[object, int]]:
        self.selected = True
        self._on_select()
        return [(object(), 1)]

    def close(self) -> None:
        self.closed = True


def _install_x11_fakes(
    monkeypatch: pytest.MonkeyPatch,
    backend: _Backend,
) -> tuple[_Display, _Selector]:
    event = SimpleNamespace(type=28, atom=99)
    display = _Display(event)
    selector = _Selector(lambda: setattr(backend, "visible", True))
    modules = {
        "Xlib.display": SimpleNamespace(Display=lambda: display),
        "Xlib.X": SimpleNamespace(
            PropertyChangeMask=1,
            PropertyNotify=28,
        ),
    }
    monkeypatch.setattr(
        acceptance,
        "import_module",
        modules.__getitem__,
    )
    monkeypatch.setattr(
        acceptance.selectors,
        "DefaultSelector",
        lambda: selector,
    )
    return display, selector


def test_wait_for_x11_app_handles_atspi_before_client_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _Backend(visible=False)
    display, selector = _install_x11_fakes(monkeypatch, backend)

    app = acceptance._await_x11_application(backend, 42)

    assert app.pid == 42
    assert backend.calls == 2
    assert selector.selected is True
    assert selector.registered is display
    assert display.root.event_mask == 1
    assert display.flushed is True
    assert selector.closed is True
    assert display.closed is True


def test_wait_for_x11_app_returns_immediately_when_already_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _Backend(visible=True)
    display, selector = _install_x11_fakes(monkeypatch, backend)

    app = acceptance._await_x11_application(backend, 42)

    assert app.pid == 42
    assert backend.calls == 1
    assert selector.selected is False
    assert selector.closed is True
    assert display.closed is True
