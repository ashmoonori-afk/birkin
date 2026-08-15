from __future__ import annotations

import pytest

from birkin.computer_use.backends.base import BackendError
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
