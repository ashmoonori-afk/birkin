from __future__ import annotations

from types import SimpleNamespace

import pytest

from birkin.computer_use.backends.base import BackendError
from birkin.computer_use.backends import linux_foreground
from birkin.computer_use.backends import macos_foreground
from birkin.computer_use.backends import windows_foreground
from birkin.computer_use.models import MutationCommand


class _Resolver:
    def bounds(self, identity: str) -> tuple[int, int, int, int] | None:
        del identity
        return (10, 10, 110, 110)

    def window_id(self, identity: str) -> str | None:
        del identity
        return "41"


class _LinuxResolver(_Resolver):
    pass


class _Quartz:
    kCGWindowListOptionOnScreenOnly = 1
    kCGWindowListExcludeDesktopElements = 2
    kCGNullWindowID = 0
    kCGWindowBounds = "bounds"
    kCGWindowNumber = "number"
    kCGScrollEventUnitPixel = 0
    kCGHIDEventTap = 0

    def __init__(self, *, window_id: int) -> None:
        self.window_id = window_id
        self.warped: tuple[float, float] | None = None

    def CGWindowListCopyWindowInfo(
        self,
        _options: int,
        _window_id: int,
    ) -> list[dict[str, object]]:
        return [
            {
                "number": self.window_id,
                "bounds": {
                    "X": 0,
                    "Y": 0,
                    "Width": 200,
                    "Height": 200,
                },
            }
        ]

    def CGWarpMouseCursorPosition(
        self,
        point: tuple[float, float],
    ) -> None:
        self.warped = point

    def CGEventCreateScrollWheelEvent(self, *args: object) -> tuple[object, ...]:
        return args

    def CGEventPost(self, _tap: int, _event: object) -> None:
        return None


def _command(
    action: str,
    *,
    axis: str | None = None,
) -> MutationCommand:
    return MutationCommand(
        action=action,
        accessibility_identity="element",
        delivery="foreground",
        value="positive",
        axis=axis,
        amount=1,
    )


def test_macos_refuses_pointer_delivery_to_occluding_window() -> None:
    quartz = _Quartz(window_id=99)

    with pytest.raises(BackendError) as error:
        macos_foreground.mutate(quartz, _Resolver(), _command("scroll"))

    assert error.value.code == "foreground_delivery_unsupported"
    assert quartz.warped is None


def test_macos_vertical_scroll_moves_pointer_to_bound_element() -> None:
    quartz = _Quartz(window_id=41)

    assert macos_foreground.mutate(
        quartz,
        _Resolver(),
        _command("scroll", axis="vertical"),
    )
    assert quartz.warped == (60.0, 60.0)


def test_macos_horizontal_scroll_refuses_without_dispatch() -> None:
    quartz = _Quartz(window_id=41)

    with pytest.raises(BackendError) as error:
        macos_foreground.mutate(
            quartz,
            _Resolver(),
            _command("scroll", axis="horizontal"),
        )

    assert error.value.code == "foreground_delivery_unsupported"
    assert quartz.warped is None


def test_windows_refuses_pointer_delivery_to_occluding_window() -> None:
    rectangle = SimpleNamespace(left=10, top=10, right=110, bottom=110)
    wrapper = SimpleNamespace(
        rectangle=lambda: rectangle,
        top_level_parent=lambda: SimpleNamespace(handle=41),
    )
    win32gui = SimpleNamespace(
        WindowFromPoint=lambda _point: 99,
        GetAncestor=lambda hwnd, _kind: hwnd,
    )

    with pytest.raises(BackendError) as error:
        windows_foreground.mutate(
            SimpleNamespace(),
            win32gui,
            {"element": wrapper},
            wrapper,
            _command("click"),
        )

    assert error.value.code == "foreground_delivery_unsupported"


def test_windows_horizontal_scroll_refuses_without_dispatch() -> None:
    rectangle = SimpleNamespace(left=10, top=10, right=110, bottom=110)
    wrapper = SimpleNamespace(
        rectangle=lambda: rectangle,
        top_level_parent=lambda: SimpleNamespace(handle=41),
    )
    win32gui = SimpleNamespace(
        WindowFromPoint=lambda _point: 41,
        GetAncestor=lambda hwnd, _kind: hwnd,
    )
    mouse = SimpleNamespace(scroll=lambda **_kwargs: pytest.fail("dispatched"))

    with pytest.raises(BackendError) as error:
        windows_foreground.mutate(
            mouse,
            win32gui,
            {"element": wrapper},
            wrapper,
            _command("scroll", axis="horizontal"),
        )

    assert error.value.code == "foreground_delivery_unsupported"


def test_windows_double_click_uses_native_double_click_api() -> None:
    rectangle = SimpleNamespace(left=10, top=10, right=110, bottom=110)
    wrapper = SimpleNamespace(
        rectangle=lambda: rectangle,
        top_level_parent=lambda: SimpleNamespace(handle=41),
    )
    win32gui = SimpleNamespace(
        WindowFromPoint=lambda _point: 41,
        GetAncestor=lambda hwnd, _kind: hwnd,
    )
    dispatched: list[dict[str, object]] = []
    mouse = SimpleNamespace(
        double_click=lambda **kwargs: dispatched.append(kwargs),
        click=lambda **_kwargs: pytest.fail("single click dispatched"),
    )

    assert windows_foreground.mutate(
        mouse,
        win32gui,
        {"element": wrapper},
        wrapper,
        _command("double_click"),
    )
    assert dispatched == [{"button": "left", "coords": (60, 60)}]


class _Window:
    def __init__(
        self,
        window_id: int,
        *,
        parent: _Window | None = None,
    ) -> None:
        self.id = window_id
        self.parent = parent
        self.children: list[_Window] = []

    def query_tree(self) -> SimpleNamespace:
        return SimpleNamespace(
            parent=self.parent,
            children=getattr(self, "children", []),
        )

    def get_attributes(self) -> SimpleNamespace:
        return SimpleNamespace(map_state=2)

    def get_geometry(self) -> SimpleNamespace:
        return SimpleNamespace(width=200, height=200)

    def translate_coords(
        self,
        _root: _Window,
        _x: int,
        _y: int,
    ) -> SimpleNamespace:
        return SimpleNamespace(x=0, y=0)


def test_linux_refuses_pointer_delivery_to_occluding_window() -> None:
    root = _Window(1)
    expected = _Window(41, parent=root)
    occluder = _Window(99, parent=root)
    root.children = [expected, occluder]
    display = SimpleNamespace(
        screen=lambda: SimpleNamespace(root=root),
        create_resource_object=lambda _kind, _xid: expected,
    )
    atspi = _LinuxResolver()

    with pytest.raises(BackendError) as error:
        linux_foreground._require_topmost(
            display,
            atspi,
            _command("click"),
            (60, 60),
            SimpleNamespace(IsViewable=2),
        )

    assert error.value.code == "foreground_delivery_unsupported"


def test_release_helpers_do_not_cancel_unowned_user_input() -> None:
    assert macos_foreground.release_inputs(object()) == ()
    assert windows_foreground.release_inputs(object()) == ()
    assert linux_foreground.release_inputs(object()) == ()
