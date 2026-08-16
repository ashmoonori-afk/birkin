"""Shipping action authority and workspace journal wiring."""

from __future__ import annotations

import uuid
from pathlib import Path
from time import monotonic
from typing import final

from birkin import store
from birkin.browser_aside_action import BrowserActionAuthority
from birkin.browser_aside_engine import BrowserRuntimeStatus
from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_events import BrowserEventBridge
from birkin.browser_aside_playwright import PersistentBrowserRuntime
from birkin.browser_aside_policy import (
    BrowserEgressPolicy,
    browser_action_authority,
)
from birkin.browser_aside_requests import BrowserRequestAuthority
from birkin.browser_aside_store import FrameBlob


@final
class BrowserOrchestration:
    def __init__(
        self,
        *,
        session_id: str,
        workspace_session_id: str,
        generation: int,
        browser_root: Path,
        policy: BrowserEgressPolicy,
        actor_id: str = "human:web",
        control_epoch: int = 1,
        event_cursor_start: int = 0,
    ) -> None:
        self._session_id = session_id
        self._generation = generation
        self._control_epoch = control_epoch
        self._actions: BrowserActionAuthority = browser_action_authority(
            egress=policy.gate,
            secrets=(),
            jail_root=str(browser_root / "exchange"),
        )
        self._events = BrowserEventBridge(
            session_id=workspace_session_id,
            actor_id=actor_id,
            clock=monotonic,
            append=store.append_ledger,
            browser_session_id=session_id,
            browser_generation=generation,
            browser_revision=1,
            cursor_start=event_cursor_start,
        )
        self._requests = BrowserRequestAuthority(
            policy=policy,
            actions=self._actions,
            events=self._events,
        )

    def started(self) -> None:
        _ = self._events.emit(
            "browser.started",
            command_id=None,
            payload={
                "browser_session_id": self._session_id,
                "generation": self._generation,
            },
        )
        _ = self._events.emit(
            "tab.opened",
            command_id=None,
            payload={
                "tab_id": "primary",
                "tab_revision": 1,
                "position": 0,
                "active": True,
                "source": "user",
                "opener_tab_id": None,
            },
        )

    @property
    def requests(self) -> BrowserRequestAuthority:
        return self._requests

    @property
    def cursor(self) -> int:
        return self._events.cursor

    def update_authority(
        self,
        actor_id: str,
        control_epoch: int,
    ) -> None:
        self._events.set_authority(actor_id)
        self._control_epoch = control_epoch

    def navigate(
        self,
        runtime: PersistentBrowserRuntime,
        url: str,
    ) -> BrowserRuntimeStatus:
        decision = self._actions.decide(
            kind="navigate",
            source="web_human",
            url=url,
            gesture="web-omnibox",
        )
        if decision.result != "allow":
            unsupported = decision.code == "external_protocol_denied"
            raise BrowserAsideError(
                (
                    "unsupported_scheme"
                    if unsupported
                    else decision.code or "browser_action_denied"
                ),
                (
                    "Only http and https navigation is allowed."
                    if unsupported
                    else "Browser navigation was denied by policy."
                ),
                400 if unsupported else 403,
            )
        operation_id = uuid.uuid4().hex
        command_id = f"browser-command-{operation_id}"
        _ = self._events.emit(
            "action.requested",
            command_id=command_id,
            payload={
                "action_id": operation_id,
                "action_kind": "navigation",
                "tab_id": "primary",
                "control_epoch": self._control_epoch,
                "state": "admitted",
                "approval_id": None,
            },
        )
        _ = self._events.emit(
            "navigation.started",
            command_id=command_id,
            payload={
                "operation_id": operation_id,
                "tab_id": "primary",
                "document_revision": 1,
                "mode": "navigate",
                "target_class": "policy_validated",
                "same_origin": False,
            },
        )
        self._requests.admit_navigation(url)
        try:
            status = runtime.navigate(url)
        except BrowserAsideError as exc:
            _ = self._events.emit(
                "error.raised",
                command_id=command_id,
                payload={
                    "error_id": operation_id,
                    "code": exc.code,
                    "recoverable": True,
                },
            )
            _ = self._events.finish_operation(
                operation_id,
                command_id=command_id,
                result="failed",
            )
            raise
        self._events.set_browser_revision(
            generation=status.browser_generation,
            revision=status.browser_revision,
        )
        _ = self._events.finish_operation(
            operation_id,
            command_id=command_id,
            result="succeeded",
        )
        return status

    def viewport_ready(
        self,
        status: BrowserRuntimeStatus,
        frame: FrameBlob,
    ) -> None:
        self._events.set_browser_revision(
            generation=status.browser_generation,
            revision=status.browser_revision,
        )
        _ = self._events.viewport_ready(
            generation=status.browser_generation,
            frame_revision=status.frame_revision,
            frame_digest=frame.digest,
            frame_ref=frame.ref,
        )

    def stopped(self, cleanup_state: str = "clean") -> None:
        _ = self._events.emit(
            "browser.stopped",
            command_id=None,
            payload={
                "reason": "explicit_close",
                "cleanup_state": cleanup_state,
                "closed_tab_count": 1,
            },
        )
