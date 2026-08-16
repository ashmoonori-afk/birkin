from __future__ import annotations

from types import SimpleNamespace

import pytest

from birkin.computer_use.backends.base import BackendError, FocusSnapshot
from birkin.computer_use.backends.windows import WindowsBackend
from birkin.computer_use.models import MutationCommand


class _EditWrapper:
    def __init__(self) -> None:
        self.value = ""
        self.iface_value = _ValuePattern(self)

    def set_edit_text(self, value: str) -> None:
        self.value = value


class _ValuePattern:
    def __init__(self, wrapper: _EditWrapper) -> None:
        self._wrapper = wrapper

    @property
    def CurrentValue(self) -> str:
        return self._wrapper.value


class _MagicWindowSpecification:
    def __getattr__(self, _name: str) -> _MagicWindowSpecification:
        return self

    def __call__(self, *_args: object, **_kwargs: object) -> None:
        raise AttributeError("not a concrete UIA wrapper")


class _NoPatternInterfaceError(Exception):
    pass


class _InvokeWrapper:
    def __init__(self, *, available: bool, name: str) -> None:
        self.available = available
        self.name = name
        self.element_info = SimpleNamespace(
            process_id=7,
            runtime_id=(1 if available else 0,),
            automation_id=name,
            is_password=False,
            control_type="Button" if available else "Window",
            name=name,
            element=SimpleNamespace(
                CurrentIsPassword=False,
            ),
        )

    @property
    def iface_invoke(self) -> object:
        if not self.available:
            raise _NoPatternInterfaceError
        return object()

    def invoke(self) -> None:
        return None

    def window_text(self) -> str:
        return self.name


def _backend_with(wrapper: object) -> WindowsBackend:
    backend = object.__new__(WindowsBackend)
    backend._elements = {"element": wrapper}
    return backend


def _type_command() -> MutationCommand:
    return MutationCommand(
        action="type",
        accessibility_identity="element",
        delivery="background",
        value="typed",
        mode="replace",
    )


def test_windows_type_uses_concrete_edit_wrapper_method() -> None:
    wrapper = _EditWrapper()
    backend = _backend_with(wrapper)

    assert backend.mutate(_type_command()) is True
    assert wrapper.value == "typed"
    assert backend._wrapper_value(wrapper) == "typed"


def test_windows_magic_spec_never_impersonates_value_pattern() -> None:
    backend = _backend_with(_MagicWindowSpecification())

    with pytest.raises(BackendError) as error:
        backend.mutate(_type_command())

    assert error.value.code == "background_delivery_unsupported"


def test_windows_reports_press_only_for_available_uia_invoke_pattern() -> None:
    backend = object.__new__(WindowsBackend)
    setattr(backend, "_no_pattern_interface_error", _NoPatternInterfaceError)

    window = backend._observed(
        _InvokeWrapper(
            available=False,
            name="Birkin Computer Use QA Fixture",
        )
    )
    button = backend._observed(
        _InvokeWrapper(
            available=True,
            name="Increment synthetic counter",
        )
    )

    assert window.supported_actions == frozenset()
    assert button.supported_actions == frozenset({"press"})


def test_windows_focus_restore_uses_pywinauto_pointer_api() -> None:
    backend = object.__new__(WindowsBackend)
    foreground: list[int] = []
    pointer: list[tuple[int, int]] = []
    backend.win32gui = SimpleNamespace(
        SetForegroundWindow=lambda hwnd: foreground.append(hwnd),
    )
    backend.mouse = SimpleNamespace(
        move=lambda *, coords: pointer.append(coords),
    )

    restored = backend.restore_focus(
        FocusSnapshot(
            frontmost_pid=7,
            focused_window_id="41",
            pointer=(12, 34),
            space_id=None,
        )
    )

    assert restored is True
    assert foreground == [41]
    assert pointer == [(12, 34)]
