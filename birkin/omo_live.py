"""Authenticated control of already-running OMO sessions."""

from __future__ import annotations

import json
import socket
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .omo_bridge import (
    DEFAULT_TIMEOUT,
    MAX_RESPONSE_BYTES,
    PROTOCOL,
    LiveSessionRegistration,
    default_registry_roots,
    load_registrations,
)
from .omo_rpc import JsonObject, JsonValue, OmoState, RpcError


@dataclass(frozen=True, slots=True)
class DeliveryAck:
    """A live session's acknowledgement for one accepted request."""

    session_id: str
    request_id: str
    accepted: bool
    replayed: bool


@dataclass(frozen=True, slots=True)
class _BridgeRequest:
    operation: str
    message: str | None = None
    request_id: str | None = None


class OmoLiveClient:
    """Send authenticated requests to endpoints owned by live OMO sessions."""

    def __init__(
        self,
        registry_roots: Sequence[Path] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._roots: tuple[Path, ...] = (
            tuple(registry_roots)
            if registry_roots is not None
            else default_registry_roots()
        )
        self._timeout: float = timeout
        self._selected_id: str | None = None
        self._lock: threading.Lock = threading.Lock()

    def switch_session(self, path: Path) -> None:
        """Select a live session using its transcript's exact header ID."""
        try:
            with path.open(encoding="utf-8") as handle:
                decoded = cast(object, json.loads(handle.readline()))
            if not isinstance(decoded, dict):
                raise RpcError("OMO session header is not an object.")
            header = cast(JsonObject, decoded)
            session_id = header.get("id")
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RpcError(f"Could not read OMO session identity: {exc}") from exc
        if not isinstance(session_id, str) or not session_id:
            raise RpcError("OMO session file has no exact session ID.")
        self.select_session(session_id)

    def select_session(self, session_id: str) -> None:
        """Select an exact live ID after an authenticated liveness probe."""
        _ = self._resolve(session_id)
        with self._lock:
            self._selected_id = session_id

    def prompt(self, message: str) -> str:
        ack = self._send_selected("prompt", message)
        return f"{ack.session_id} accepted request {ack.request_id}"

    def steer(self, message: str) -> None:
        _ = self._send_selected("steer", message)

    def abort(self) -> None:
        _ = self._send_selected("abort")

    def get_state(self) -> OmoState:
        session_id = self._selected()
        response = self._send(
            self._resolve(session_id),
            _BridgeRequest("state"),
        )
        return OmoState(
            session_id=session_id,
            is_streaming=response.get("is_streaming") is True,
        )

    def get_last_assistant_text(self) -> str | None:
        session_id = self._selected()
        response = self._send(
            self._resolve(session_id),
            _BridgeRequest("last"),
        )
        text = response.get("text")
        return text if isinstance(text, str) else None

    def send_to_sessions(
        self,
        session_ids: Sequence[str],
        message: str,
    ) -> tuple[DeliveryAck, ...]:
        """Deliver once to each unique exact ID after resolving every target."""
        unique_ids = tuple(dict.fromkeys(session_ids))
        if not unique_ids:
            raise RpcError("At least one exact live session ID is required.")
        registrations = tuple(self._resolve(session_id) for session_id in unique_ids)
        return tuple(
            self._ack(
                registration,
                self._send(
                    registration,
                    _BridgeRequest("prompt", message),
                ),
            )
            for registration in registrations
        )

    def send_to_session(
        self,
        session_id: str,
        message: str,
        *,
        request_id: str | None = None,
    ) -> DeliveryAck:
        """Deliver one request, optionally replaying its idempotency key."""
        registration = self._resolve(session_id)
        response = self._send(
            registration,
            _BridgeRequest("prompt", message, request_id),
        )
        return self._ack(registration, response)

    def close(self) -> None:
        """Release local selection state; live endpoints remain session-owned."""
        with self._lock:
            self._selected_id = None

    def _selected(self) -> str:
        with self._lock:
            session_id = self._selected_id
        if session_id is None:
            raise RpcError("Select a live OMO session first.")
        return session_id

    def _send_selected(
        self,
        operation: str,
        message: str | None = None,
    ) -> DeliveryAck:
        session_id = self._selected()
        registration = self._resolve(session_id)
        response = self._send(
            registration,
            _BridgeRequest(operation, message),
        )
        return self._ack(registration, response)

    def _resolve(self, session_id: str) -> LiveSessionRegistration:
        candidates = [
            registration
            for registration in self._registrations()
            if registration.session_id == session_id
        ]
        live: list[LiveSessionRegistration] = []
        errors: list[str] = []
        for registration in candidates:
            try:
                _ = self._send(registration, _BridgeRequest("state"))
                live.append(registration)
            except RpcError as exc:
                errors.append(str(exc))
        if len(live) > 1:
            raise RpcError(f"Live OMO session ID is ambiguous: {session_id}")
        if len(live) == 1:
            return live[0]
        if any("unauthorized" in error.lower() for error in errors):
            raise RpcError(f"Live OMO session is unauthorized: {session_id}")
        raise RpcError(f"OMO session is not live: {session_id}")

    def _registrations(self) -> tuple[LiveSessionRegistration, ...]:
        return load_registrations(self._roots)

    def _send(
        self,
        registration: LiveSessionRegistration,
        bridge_request: _BridgeRequest,
    ) -> JsonObject:
        selected_request_id = bridge_request.request_id or uuid.uuid4().hex
        request: JsonObject = {
            "protocol": PROTOCOL,
            "request_id": selected_request_id,
            "session_id": registration.session_id,
            "token": registration.token,
            "operation": bridge_request.operation,
        }
        if bridge_request.message is not None:
            request["message"] = bridge_request.message
        payload = (json.dumps(request, separators=(",", ":")) + "\n").encode()
        try:
            with socket.create_connection(
                (registration.host, registration.port),
                timeout=self._timeout,
            ) as connection:
                connection.settimeout(self._timeout)
                connection.sendall(payload)
                with connection.makefile("rb") as reader:
                    raw = reader.readline(MAX_RESPONSE_BYTES + 1)
        except (OSError, TimeoutError) as exc:
            raise RpcError(
                f"Live OMO session is unreachable: {registration.session_id}"
            ) from exc
        if not raw.endswith(b"\n") or len(raw) > MAX_RESPONSE_BYTES:
            raise RpcError("Live OMO bridge returned an invalid response frame.")
        try:
            decoded = cast(object, json.loads(raw))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RpcError("Live OMO bridge returned invalid JSON.") from exc
        if not isinstance(decoded, dict):
            raise RpcError("Live OMO bridge response is not an object.")
        response = cast(JsonObject, decoded)
        self._validate_response(registration, selected_request_id, response)
        return response

    @staticmethod
    def _validate_response(
        registration: LiveSessionRegistration,
        request_id: str,
        response: JsonObject,
    ) -> None:
        if (
            response.get("protocol") != PROTOCOL
            or response.get("request_id") != request_id
            or response.get("session_id") != registration.session_id
        ):
            raise RpcError("Live OMO bridge acknowledgement identity mismatch.")
        if response.get("ok") is not True:
            error: JsonValue = response.get("error")
            detail = error if isinstance(error, str) else "request rejected"
            raise RpcError(
                f"Live OMO session {registration.session_id}: {detail}"
            )

    @staticmethod
    def _ack(
        registration: LiveSessionRegistration,
        response: JsonObject,
    ) -> DeliveryAck:
        request_id = response.get("request_id")
        if not isinstance(request_id, str):
            raise RpcError("Live OMO bridge acknowledgement has no request ID.")
        return DeliveryAck(
            session_id=registration.session_id,
            request_id=request_id,
            accepted=response.get("accepted") is True,
            replayed=response.get("replayed") is True,
        )
