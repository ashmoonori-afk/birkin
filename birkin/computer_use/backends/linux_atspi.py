"""Bounded AT-SPI capture and semantic actions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from ..models import MutationCommand, ObservedElement, ObservedWindow
from .base import BackendError


@dataclass(frozen=True, slots=True)
class _Locator:
    window: ObservedWindow
    path: tuple[int, ...]
    role: str
    identity: str


class LinuxATSPi:
    def __init__(self, api: Any):
        self.api = api
        self._locators: dict[str, _Locator] = {}

    def capture(self, window: ObservedWindow) -> tuple[ObservedElement, ...]:
        root = self._find_window(window)
        output: list[ObservedElement] = []
        self._walk(root, window, (), output, depth=0)
        return tuple(output)

    def read(self, identity: str) -> ObservedElement | None:
        locator = self._locators.get(identity)
        if locator is None:
            return None
        element = self._resolve(locator)
        return (
            self._observed(element, locator.path, locator.identity)
            if element is not None
            else None
        )

    def bounds(self, identity: str) -> tuple[int, int, int, int] | None:
        locator = self._locators.get(identity)
        if locator is None:
            return None
        element = self._resolve(locator)
        if element is None:
            return None
        try:
            extents = element.queryComponent().getExtents(self.api.DESKTOP_COORDS)
        except NotImplementedError:
            return None
        return (
            int(extents.x),
            int(extents.y),
            int(extents.x + extents.width),
            int(extents.y + extents.height),
        )

    def window_id(self, identity: str) -> str | None:
        locator = self._locators.get(identity)
        return locator.window.native_window_id if locator is not None else None

    def mutate(self, command: MutationCommand) -> bool:
        locator = self._locators.get(command.accessibility_identity)
        if locator is None:
            raise BackendError("stale_ref", "The AT-SPI element changed.")
        element = self._resolve(locator)
        if element is None:
            raise BackendError("stale_ref", "The AT-SPI element changed.")
        if command.action == "type":
            try:
                element.queryEditableText().setTextContents(str(command.value or ""))
                return True
            except NotImplementedError as exc:
                raise BackendError(
                    "background_delivery_unsupported",
                    "AT-SPI EditableText is unavailable.",
                ) from exc
        if command.action == "click":
            action = element.queryAction()
            for index in range(action.nActions):
                if action.getName(index).casefold() in {
                    "click",
                    "press",
                    "activate",
                }:
                    return bool(action.doAction(index))
        raise BackendError(
            "background_delivery_unsupported",
            "AT-SPI has no exact semantic action for this request.",
        )

    def _find_window(self, window: ObservedWindow) -> Any:
        desktop = self.api.Registry.getDesktop(0)
        applications = [desktop[index] for index in range(desktop.childCount)]
        matching_apps = [
            app for app in applications if int(app.get_process_id()) == window.pid
        ]
        if len(matching_apps) != 1:
            raise BackendError(
                "identity_ambiguous" if matching_apps else "target_gone",
                "The X11 PID could not be correlated to one AT-SPI app.",
            )
        candidates = [
            matching_apps[0][index] for index in range(matching_apps[0].childCount)
        ]
        matches = [
            candidate
            for candidate in candidates
            if self._window_matches(candidate, window)
        ]
        if len(matches) != 1:
            raise BackendError(
                "identity_ambiguous" if matches else "target_gone",
                "The XID could not be uniquely correlated to AT-SPI.",
            )
        return matches[0]

    def _window_matches(self, element: Any, window: ObservedWindow) -> bool:
        try:
            extents = element.queryComponent().getExtents(self.api.DESKTOP_COORDS)
        except NotImplementedError:
            return False
        left, top, right, bottom = window.bounds
        ax_left = int(extents.x)
        ax_top = int(extents.y)
        ax_right = ax_left + int(extents.width)
        ax_bottom = ax_top + int(extents.height)
        overlap_width = max(0, min(right, ax_right) - max(left, ax_left))
        overlap_height = max(0, min(bottom, ax_bottom) - max(top, ax_top))
        overlap = overlap_width * overlap_height
        x11_area = max(1, (right - left) * (bottom - top))
        atspi_area = max(1, int(extents.width) * int(extents.height))
        return overlap / min(x11_area, atspi_area) >= 0.75

    def _walk(
        self,
        element: Any,
        window: ObservedWindow,
        path: tuple[int, ...],
        output: list[ObservedElement],
        *,
        depth: int,
    ) -> None:
        if depth > 12 or len(output) >= 500:
            return
        role = str(element.getRoleName())
        identity = self._identity(window, path, role)
        self._locators[identity] = _Locator(window, path, role, identity)
        output.append(self._observed(element, path, identity))
        for index in range(min(int(element.childCount), 100)):
            self._walk(
                element[index],
                window,
                (*path, index),
                output,
                depth=depth + 1,
            )

    def _resolve(self, locator: _Locator) -> Any | None:
        try:
            element = self._find_window(locator.window)
            for index in locator.path:
                element = element[index]
            if str(element.getRoleName()) != locator.role:
                return None
            return element
        except (BackendError, IndexError):
            return None

    def _observed(
        self,
        element: Any,
        path: tuple[int, ...],
        identity: str,
    ) -> ObservedElement:
        actions: set[str] = set()
        try:
            action = element.queryAction()
            for index in range(action.nActions):
                name = action.getName(index).casefold()
                if name in {"click", "press", "activate"}:
                    actions.add("press")
        except NotImplementedError:
            pass
        value: object | None = str(element.name or "")
        try:
            text = element.queryText()
            value = str(text.getText(0, -1))
        except NotImplementedError:
            pass
        try:
            element.queryEditableText()
            actions.add("set_value")
        except NotImplementedError:
            pass
        role = str(element.getRoleName())
        sensitive = "password" if "password" in role.casefold() else None
        return ObservedElement(
            accessibility_identity=identity,
            accessibility_path=tuple(map(str, path)),
            role=role,
            name=str(element.name or ""),
            value=value,
            supported_actions=frozenset(actions),
            sensitive_category=sensitive,
        )

    @staticmethod
    def _identity(
        window: ObservedWindow,
        path: tuple[int, ...],
        role: str,
    ) -> str:
        raw = "|".join(
            (
                str(window.pid),
                window.process_generation,
                window.native_window_id,
                "/".join(map(str, path)),
                role,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
