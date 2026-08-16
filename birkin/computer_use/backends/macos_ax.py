"""Bounded macOS AX capture and semantic mutation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import MutationCommand, ObservedElement, ObservedWindow
from .base import BackendError
from .macos_native import ax_identity, ax_pair


@dataclass(frozen=True, slots=True)
class _Locator:
    window: ObservedWindow
    child_indexes: tuple[int, ...]
    role: str
    identifier: str


class MacOSAX:
    def __init__(self, application_services: Any):
        self.api = application_services
        self._locators: dict[str, _Locator] = {}

    def trusted(self) -> bool:
        return bool(self.api.AXIsProcessTrusted())

    def capture(self, window: ObservedWindow) -> tuple[ObservedElement, ...]:
        if not self.trusted():
            raise BackendError(
                "permission_required",
                "macOS Accessibility permission is required.",
            )
        root = self._find_window(window)
        elements: list[ObservedElement] = []
        self._walk(root, window, (), elements, depth=0)
        return tuple(elements)

    def read(self, identity: str) -> ObservedElement | None:
        locator = self._locators.get(identity)
        if locator is None or not self.trusted():
            return None
        element = self._resolve(locator)
        if element is None:
            return None
        return self._observed(element, locator, identity)

    def bounds(self, identity: str) -> tuple[int, int, int, int] | None:
        locator = self._locators.get(identity)
        if locator is None:
            return None
        element = self._resolve(locator)
        if element is None:
            return None
        position = ax_pair(
            self.api,
            self._copy(element, self.api.kAXPositionAttribute),
            self.api.kAXValueCGPointType,
        )
        size = ax_pair(
            self.api,
            self._copy(element, self.api.kAXSizeAttribute),
            self.api.kAXValueCGSizeType,
        )
        if position is None or size is None:
            return None
        left, top = position
        width, height = size
        return (
            round(left),
            round(top),
            round(left + width),
            round(top + height),
        )

    def window_id(self, identity: str) -> str | None:
        locator = self._locators.get(identity)
        return locator.window.native_window_id if locator is not None else None

    def mutate(self, command: MutationCommand) -> bool:
        locator = self._locators.get(command.accessibility_identity)
        if locator is None:
            raise BackendError("stale_ref", "The AX element is no longer bound.")
        element = self._resolve(locator)
        if element is None:
            raise BackendError("stale_ref", "The AX element changed.")
        if command.action == "type":
            text = str(command.value or "")
            if command.mode == "append":
                current = self._copy(element, self.api.kAXValueAttribute)
                text = f"{current or ''}{text}"
            elif command.mode == "insert":
                raise BackendError(
                    "background_delivery_unsupported",
                    "AX cannot prove the current insertion point.",
                )
            error = self.api.AXUIElementSetAttributeValue(
                element,
                self.api.kAXValueAttribute,
                text,
            )
        else:
            if command.action == "scroll" and command.axis != "vertical":
                raise BackendError(
                    "background_delivery_unsupported",
                    "AX semantic scrolling supports only the vertical axis.",
                )
            action = {
                "click": self.api.kAXPressAction,
                "scroll": (
                    self.api.kAXIncrementAction
                    if command.value != "negative"
                    else self.api.kAXDecrementAction
                ),
            }.get(command.action)
            if action is None:
                raise BackendError(
                    "background_delivery_unsupported",
                    "The AX element has no semantic action for this request.",
                )
            repetitions = (
                max(1, min(100, int(command.amount or 1)))
                if command.action == "scroll"
                else 1
            )
            error = self.api.kAXErrorSuccess
            for _ in range(repetitions):
                error = self.api.AXUIElementPerformAction(element, action)
                if error != self.api.kAXErrorSuccess:
                    break
        if error != self.api.kAXErrorSuccess:
            raise BackendError(
                "background_delivery_unsupported",
                f"The AX semantic action failed with code {error}.",
                effect_possible=True,
            )
        return True

    def _find_window(self, window: ObservedWindow) -> Any:
        app = self.api.AXUIElementCreateApplication(window.pid)
        candidates = self._copy(app, self.api.kAXWindowsAttribute)
        if not isinstance(candidates, (list, tuple)):
            raise BackendError("target_gone", "The AX window is unavailable.")
        matches = [
            candidate
            for candidate in candidates
            if self._window_matches(candidate, window)
        ]
        if len(matches) != 1:
            raise BackendError(
                "identity_ambiguous" if matches else "target_gone",
                "The CGWindowID could not be uniquely correlated to AX.",
            )
        return matches[0]

    def _window_matches(self, element: Any, window: ObservedWindow) -> bool:
        position = ax_pair(
            self.api,
            self._copy(element, self.api.kAXPositionAttribute),
            self.api.kAXValueCGPointType,
        )
        size = ax_pair(
            self.api,
            self._copy(element, self.api.kAXSizeAttribute),
            self.api.kAXValueCGSizeType,
        )
        if position is None or size is None:
            return False
        left, top, right, bottom = window.bounds
        ax_left = round(position[0])
        ax_top = round(position[1])
        ax_right = ax_left + round(size[0])
        ax_bottom = ax_top + round(size[1])
        overlap_width = max(0, min(right, ax_right) - max(left, ax_left))
        overlap_height = max(0, min(bottom, ax_bottom) - max(top, ax_top))
        overlap = overlap_width * overlap_height
        quartz_area = max(1, (right - left) * (bottom - top))
        ax_area = max(1, round(size[0]) * round(size[1]))
        return overlap / min(quartz_area, ax_area) >= 0.75

    def _walk(
        self,
        element: Any,
        window: ObservedWindow,
        indexes: tuple[int, ...],
        output: list[ObservedElement],
        *,
        depth: int,
    ) -> None:
        if depth > 12 or len(output) >= 500:
            return
        role = str(self._copy(element, self.api.kAXRoleAttribute) or "unknown")
        identifier = str(self._copy(element, self.api.kAXIdentifierAttribute) or "")
        identity = ax_identity(window, indexes, role, identifier)
        locator = _Locator(window, indexes, role, identifier)
        self._locators[identity] = locator
        output.append(self._observed(element, locator, identity))
        children = self._copy(element, self.api.kAXChildrenAttribute)
        if not isinstance(children, (list, tuple)):
            return
        for index, child in enumerate(children[:100]):
            self._walk(
                child,
                window,
                (*indexes, index),
                output,
                depth=depth + 1,
            )

    def _resolve(self, locator: _Locator) -> Any | None:
        try:
            element = self._find_window(locator.window)
            for index in locator.child_indexes:
                children = self._copy(element, self.api.kAXChildrenAttribute)
                if not isinstance(children, (list, tuple)):
                    return None
                element = children[index]
            role = str(self._copy(element, self.api.kAXRoleAttribute) or "unknown")
            identifier = str(self._copy(element, self.api.kAXIdentifierAttribute) or "")
            if role != locator.role or identifier != locator.identifier:
                return None
            return element
        except (BackendError, IndexError):
            return None

    def _observed(
        self,
        element: Any,
        locator: _Locator,
        identity: str,
    ) -> ObservedElement:
        name = str(
            self._copy(element, self.api.kAXTitleAttribute)
            or self._copy(element, self.api.kAXDescriptionAttribute)
            or ""
        )
        value = self._copy(element, self.api.kAXValueAttribute)
        if not isinstance(value, (str, int, float, bool, type(None))):
            value = None
        actions = self._actions(element)
        sensitive = (
            "password"
            if "secure" in locator.role.casefold()
            or "secure"
            in str(self._copy(element, self.api.kAXSubroleAttribute) or "").casefold()
            else None
        )
        return ObservedElement(
            accessibility_identity=identity,
            accessibility_path=tuple(str(index) for index in locator.child_indexes),
            role=locator.role,
            name=name,
            value=value,
            supported_actions=actions,
            sensitive_category=sensitive,
        )

    def _actions(self, element: Any) -> frozenset[str]:
        error, raw = self.api.AXUIElementCopyActionNames(element, None)
        if error != self.api.kAXErrorSuccess or not raw:
            return frozenset()
        mapped = {
            self.api.kAXPressAction: "press",
            self.api.kAXIncrementAction: "scroll",
            self.api.kAXDecrementAction: "scroll",
        }
        actions = {mapped[action] for action in raw if action in mapped}
        writable = self.api.AXUIElementIsAttributeSettable(
            element,
            self.api.kAXValueAttribute,
            None,
        )
        if (
            isinstance(writable, tuple)
            and writable[0] == self.api.kAXErrorSuccess
            and bool(writable[1])
        ):
            actions.add("set_value")
        return frozenset(actions)

    def _copy(self, element: Any, attribute: str) -> Any:
        error, value = self.api.AXUIElementCopyAttributeValue(
            element,
            attribute,
            None,
        )
        return value if error == self.api.kAXErrorSuccess else None
