from __future__ import annotations

from dataclasses import replace
from threading import Event

from birkin.computer_use.capabilities import (
    DisplayServer,
    PermissionState,
    PlatformProbe,
)
from birkin.computer_use.models import (
    BackendCapture,
    FocusSnapshot,
    MutationCommand,
    ObservedApp,
    ObservedElement,
    ObservedWindow,
)


class FakeBackend:
    backend_id = "fake-native"
    foreground_actions = frozenset(
        {
            "click",
            "double_click",
            "right_click",
            "middle_click",
            "drag",
            "scroll",
            "type",
            "key",
        }
    )

    def __init__(self) -> None:
        self.app = ObservedApp(
            pid=420,
            process_generation="launch-1",
            native_identity="org.birkin.QAFixture",
            name="Birkin QA Fixture",
        )
        self.window = ObservedWindow(
            pid=420,
            process_generation="launch-1",
            native_window_id="window-99",
            window_generation=1,
            title="Birkin QA Fixture",
            bounds=(10, 20, 410, 320),
        )
        self.element = ObservedElement(
            accessibility_identity="AXTextField:value",
            accessibility_path=("AXWindow:0", "AXTextField:0"),
            role="text_field",
            name="Fixture value",
            value="before",
            supported_actions=frozenset({"set_value", "press"}),
        )
        self.mutation_count = 0
        self.last_command: MutationCommand | None = None
        self.foreground_count = 0
        self.wait_count = 0
        self.change_focus_on_mutation = False
        self.move_pointer_on_mutation = False
        self.restore_count = 0
        self.release_count = 0
        self._focus_pid = 777
        self._pointer = (50, 60)
        self.block_mutation = False
        self.mutation_started = Event()
        self.mutation_continue = Event()
        self.readable = True

    def probe(self) -> PlatformProbe:
        return PlatformProbe(
            platform="darwin",
            display_server=DisplayServer.QUARTZ,
            interactive=True,
            accessibility=PermissionState.GRANTED,
            screen_capture=PermissionState.GRANTED,
            responsible_process="org.birkin.QAFixture",
        )

    def list_apps(self) -> tuple[ObservedApp, ...]:
        return (self.app,)

    def list_windows(
        self,
        app: ObservedApp | None,
    ) -> tuple[ObservedWindow, ...]:
        assert app is None or app == self.app
        return (self.window,)

    def capture(
        self,
        window: ObservedWindow,
        mode: str,
    ) -> BackendCapture:
        assert window == self.window
        return BackendCapture(
            ui_fingerprint=f"{self.element.value}:{mode}",
            elements=(self.element,),
            image_bytes=b"\x89PNG\r\nfixture" if mode != "ax" else None,
            media_type="image/png" if mode != "ax" else None,
            width=400 if mode != "ax" else None,
            height=300 if mode != "ax" else None,
            isolated=True,
        )

    def mutate(self, command: MutationCommand) -> bool:
        self.mutation_count += 1
        self.last_command = command
        if self.block_mutation:
            self.mutation_started.set()
            if not self.mutation_continue.wait(timeout=2):
                raise TimeoutError("test mutation was not released")
        if self.change_focus_on_mutation:
            self._focus_pid = 420
        if self.move_pointer_on_mutation:
            self._pointer = (80, 90)
        if command.delivery == "foreground":
            self.foreground_count += 1
        if command.action == "type":
            self.element = replace(self.element, value=command.value)
        elif command.action in {
            "click",
            "double_click",
            "right_click",
            "middle_click",
        }:
            self.element = replace(self.element, value="clicked")
        elif command.action == "drag":
            self.element = replace(self.element, value="dragged")
        elif command.action == "scroll":
            self.element = replace(self.element, value="scrolled")
        elif command.action == "key":
            self.element = replace(
                self.element,
                value=f"key:{command.value}",
            )
        return True

    def focus_state(self) -> FocusSnapshot:
        return FocusSnapshot(
            frontmost_pid=self._focus_pid,
            focused_window_id="user-window",
            pointer=self._pointer,
            space_id=None,
        )

    def can_restore_focus(self, snapshot: FocusSnapshot) -> bool:
        return snapshot.frontmost_pid is not None

    def restore_focus(self, snapshot: FocusSnapshot) -> bool:
        self.restore_count += 1
        self._focus_pid = snapshot.frontmost_pid
        return True

    def release_inputs(self) -> tuple[str, ...]:
        self.release_count += 1
        return ("shift", "mouse_left")

    def read_element(self, accessibility_identity: str) -> ObservedElement | None:
        if not self.readable:
            return None
        assert accessibility_identity == self.element.accessibility_identity
        return self.element
