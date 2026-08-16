from __future__ import annotations

from types import SimpleNamespace

from birkin.computer_use.backends.linux import LinuxBackend
from birkin.computer_use.backends.linux_atspi import LinuxATSPi
from birkin.computer_use.models import ObservedWindow


class _Component:
    def __init__(self, extents: SimpleNamespace) -> None:
        self._extents = extents

    def getExtents(self, _coordinates: object) -> SimpleNamespace:
        return self._extents


class _Element:
    def __init__(self, extents: SimpleNamespace) -> None:
        self._component = _Component(extents)

    def queryComponent(self) -> _Component:
        return self._component


def _window() -> ObservedWindow:
    return ObservedWindow(
        pid=42,
        process_generation="42:1",
        native_window_id="100",
        window_generation=1,
        title="Fixture",
        bounds=(100, 100, 500, 400),
    )


def test_atspi_correlation_tolerates_window_manager_frame() -> None:
    adapter = LinuxATSPi(SimpleNamespace(DESKTOP_COORDS=object()))
    element = _Element(
        SimpleNamespace(x=94, y=72, width=412, height=434),
    )

    assert adapter._window_matches(element, _window()) is True


def test_atspi_correlation_rejects_different_window_geometry() -> None:
    adapter = LinuxATSPi(SimpleNamespace(DESKTOP_COORDS=object()))
    element = _Element(
        SimpleNamespace(x=700, y=100, width=400, height=300),
    )

    assert adapter._window_matches(element, _window()) is False


def test_xid_generation_advances_after_reappearance() -> None:
    backend = object.__new__(LinuxBackend)
    backend._window_epochs = {}

    first = backend._window_generation(100, ("first",))
    stable = backend._window_generation(100, ("first",))
    backend._window_epochs[100] = (stable, ("first",), False)
    reused = backend._window_generation(100, ("first",))

    assert first == stable
    assert reused == stable + 1
