"""Classify and journal browser-caused effects before they execute."""

from __future__ import annotations

from threading import RLock
from typing import cast, final
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from birkin.browser_aside_action import BrowserActionAuthority
from birkin.browser_aside_engine import (
    BrowserDialog,
    BrowserDownload,
    BrowserFileChooser,
    BrowserPage,
    BrowserRoute,
)
from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_events import BrowserEventBridge
from birkin.browser_aside_policy import BrowserEgressPolicy

MAX_FORM_FIELDS = 64


@final
class BrowserRequestAuthority:
    def __init__(
        self,
        *,
        policy: BrowserEgressPolicy,
        actions: BrowserActionAuthority,
        events: BrowserEventBridge,
    ) -> None:
        self._policy = policy
        self._actions = actions
        self._events = events
        self._permits: set[str] = set()
        self._lock = RLock()

    def admit_navigation(self, url: str) -> None:
        with self._lock:
            self._permits.add(_request_key(url))

    def route(self, route: BrowserRoute) -> None:
        request = route.request
        try:
            self._policy.check_navigation(request.url)
            if request.resource_type == "websocket":
                self._deny(route, "external_protocol_denied")
                return
            if request.method not in {"GET", "HEAD"}:
                self._form(route)
                return
            if request.is_navigation_request():
                self._navigation(route)
                return
        except BrowserAsideError as exc:
            self._deny(route, exc.code)
            return
        except ValueError:
            self._deny(route, "form_payload_invalid")
            return
        route.continue_()

    def popup(self, value: object) -> None:
        popup = cast(BrowserPage, value)
        popup.close()
        self._journal("popup", "denied", "popup_blocked")

    def dialog(self, value: object) -> None:
        dialog = cast(BrowserDialog, value)
        _ = self._events.emit(
            "dialog.opened",
            command_id=None,
            payload={"dialog_id": "active", "dialog_kind": "page"},
        )
        dialog.dismiss()
        _ = self._events.emit(
            "dialog.resolved",
            command_id=None,
            payload={
                "dialog_id": "active",
                "resolution": "dismissed",
            },
        )

    def file_chooser(self, value: object) -> None:
        chooser = cast(BrowserFileChooser, value)
        chooser.set_files(())
        self._journal("upload", "denied", "upload_jail_denied")

    def download(self, value: object) -> None:
        download = cast(BrowserDownload, value)
        _ = self._events.emit(
            "download.requested",
            command_id=None,
            payload={"download_id": "active", "state": "requested"},
        )
        download.cancel()
        _ = self._events.emit(
            "download.finished",
            command_id=None,
            payload={
                "download_id": "active",
                "state": "denied",
                "result": "download_disabled",
            },
        )

    def _navigation(self, route: BrowserRoute) -> None:
        request = route.request
        key = _request_key(request.url)
        with self._lock:
            explicit = key in self._permits
            if explicit:
                self._permits.remove(key)
        redirected = request.redirected_from is not None
        if explicit or redirected:
            self._journal(
                "navigation",
                "allow",
                "explicit" if explicit else "redirect",
            )
            route.continue_()
            return
        decision = self._actions.decide(
            kind="navigate",
            source="browser_page",
            url=request.url,
        )
        self._deny(
            route,
            decision.code or "browser_navigation_not_admitted",
        )

    def _form(self, route: BrowserRoute) -> None:
        request = route.request
        fields = tuple(
            parse_qsl(
                request.post_data or "",
                keep_blank_values=True,
                max_num_fields=MAX_FORM_FIELDS,
            )
        )
        decision = self._actions.decide(
            kind="form_submit",
            source="browser_page",
            url=request.url,
            method=request.method,
            fields=fields,
        )
        self._deny(
            route,
            decision.code or "form_submit_not_admitted",
        )

    def _deny(self, route: BrowserRoute, code: str) -> None:
        route.abort("blockedbyclient")
        self._journal("browser_effect", "denied", code)

    def _journal(self, kind: str, result: str, code: str) -> None:
        _ = self._events.emit(
            "action.finished",
            command_id=None,
            payload={
                "action_kind": kind,
                "result": result,
                "code": code,
            },
        )


def _request_key(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path or "/",
        parsed.query,
        "",
    ))
