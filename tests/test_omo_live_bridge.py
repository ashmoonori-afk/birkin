from __future__ import annotations

import json
import socket
import socketserver
import subprocess
import threading
from pathlib import Path
from typing import cast, final

import pytest

from birkin.omo import OmoController
from birkin.omo_live import OmoLiveClient


@final
class _BridgeEndpoint:
    def __init__(self, session_id: str, token: str) -> None:
        self.session_id: str = session_id
        self.token: str = token
        self.deliveries: list[tuple[str, str]] = []
        self.delivery_event: threading.Event = threading.Event()
        self._responses: dict[str, dict[str, object]] = {}
        self._lock: threading.Lock = threading.Lock()
        endpoint = self

        def handle_connection(
            connection: socket.socket,
            _client_address: tuple[str, int],
            _server: socketserver.BaseServer,
        ) -> None:
            with connection.makefile("rb") as reader:
                raw = reader.readline(65_537)
            decoded = cast(object, json.loads(raw))
            if not isinstance(decoded, dict):
                raise TypeError("Bridge test request must be an object.")
            request = cast(dict[str, object], decoded)
            response = endpoint.handle(request)
            connection.sendall((json.dumps(response) + "\n").encode())

        handler = cast(type[socketserver.BaseRequestHandler], handle_connection)
        self.server: socketserver.ThreadingTCPServer = (
            socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
        )
        self.server.daemon_threads = True
        self.thread: threading.Thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def handle(self, request: dict[str, object]) -> dict[str, object]:
        request_id = str(request["request_id"])
        if request.get("token") != self.token:
            return self._response(request_id, False, error="unauthorized")
        if request.get("session_id") != self.session_id:
            return self._response(request_id, False, error="session mismatch")
        if request.get("operation") == "state":
            return self._response(request_id, True, is_streaming=False)
        with self._lock:
            cached = self._responses.get(request_id)
            if cached is not None:
                return {**cached, "replayed": True}
            message = str(request.get("message") or "")
            self.deliveries.append((request_id, message))
            response = self._response(request_id, True, accepted=True)
            self._responses[request_id] = response
            self.delivery_event.set()
            return response

    def _response(
        self,
        request_id: str,
        ok: bool,
        **payload: object,
    ) -> dict[str, object]:
        return {
            "protocol": 1,
            "request_id": request_id,
            "session_id": self.session_id,
            "ok": ok,
            **payload,
        }

    def write_registration(
        self,
        root: Path,
        *,
        token: str | None = None,
        suffix: str = "test",
    ) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{self.session_id}.{suffix}.json"
        _ = path.write_text(
            json.dumps(
                {
                    "protocol": 1,
                    "session_id": self.session_id,
                    "host": "127.0.0.1",
                    "port": self.port,
                    "token": token or self.token,
                    "pid": 1234,
                }
            ),
            encoding="utf-8",
        )
        return path

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)


def _forbid_subprocess(*args: object, **kwargs: object) -> subprocess.Popen[str]:
    raise AssertionError(f"OMO session control spawned a subprocess: {args!r} {kwargs!r}")


def test_resume_reaches_two_exact_live_sessions_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_ids = (
        "019ffe4c-0ba9-7fa2-acab-176a22fc1fd3",
        "019ffda0-c982-7ffe-badf-b952f457011e",
    )
    endpoints = [
        _BridgeEndpoint(session_id, f"token-{index:032d}")
        for index, session_id in enumerate(session_ids)
    ]
    registry = tmp_path / "live"
    for endpoint in endpoints:
        _ = endpoint.write_registration(registry)
    monkeypatch.setenv("BIRKIN_OMO_LIVE_DIR", str(registry))
    monkeypatch.setattr(subprocess, "Popen", _forbid_subprocess)

    try:
        controller = OmoController(session_roots=())
        response = controller.handle(f"/omo send-to {','.join(session_ids)} -- resume")

        assert all(endpoint.delivery_event.wait(timeout=1) for endpoint in endpoints)
        assert all(len(endpoint.deliveries) == 1 for endpoint in endpoints)
        assert all(endpoint.deliveries[0][1] == "resume" for endpoint in endpoints)
        assert all(session_id in response for session_id in session_ids)
        assert all(endpoint.deliveries[0][0] in response for endpoint in endpoints)
        assert response.count("accepted") == 2
        controller.close()
    finally:
        for endpoint in endpoints:
            endpoint.close()


def test_stale_wrong_or_replayed_target_never_crosses_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_id = "019ffe4c-0ba9-7fa2-acab-176a22fc1fd3"
    unrelated_id = "019ffda0-c982-7ffe-badf-b952f457011e"
    target = _BridgeEndpoint(target_id, "target-token-0000000000000000000000000000")
    duplicate = _BridgeEndpoint(target_id, "other-token-00000000000000000000000000000")
    unrelated = _BridgeEndpoint(unrelated_id, "unrelated-token-00000000000000000000000000")
    registry = tmp_path / "live"
    target_path = target.write_registration(registry, token="x" * 32)
    _ = unrelated.write_registration(registry)
    monkeypatch.setenv("BIRKIN_OMO_LIVE_DIR", str(registry))
    monkeypatch.setattr(subprocess, "Popen", _forbid_subprocess)

    try:
        controller = OmoController(session_roots=())

        unauthorized = controller.handle(f"/omo send-to {target_id} -- resume")
        assert "unauthorized" in unauthorized.lower()
        assert target.deliveries == []
        assert unrelated.deliveries == []

        _ = target.write_registration(registry)
        duplicate_path = duplicate.write_registration(registry, suffix="duplicate")
        ambiguous = controller.handle(f"/omo send-to {target_id} -- resume")
        assert "ambiguous" in ambiguous.lower()
        assert target.deliveries == []
        assert duplicate.deliveries == []
        assert unrelated.deliveries == []

        unknown = controller.handle("/omo send-to historical-only -- resume")
        assert "not live" in unknown.lower()
        assert unrelated.deliveries == []

        _ = duplicate_path.unlink()
        delivered = controller.handle(
            f"/omo send-to {target_id},{target_id} -- resume"
        )
        assert target.delivery_event.wait(timeout=1)
        assert len(target.deliveries) == 1
        assert target.deliveries[0][1] == "resume"
        assert delivered.count("accepted") == 1
        assert unrelated.deliveries == []
        controller.close()
    finally:
        _ = target_path.unlink(missing_ok=True)
        target.close()
        duplicate.close()
        unrelated.close()


def test_same_request_id_replay_is_acknowledged_without_redelivery(
    tmp_path: Path,
) -> None:
    session_id = "019ffe4c-0ba9-7fa2-acab-176a22fc1fd3"
    endpoint = _BridgeEndpoint(
        session_id,
        "replay-token-000000000000000000000000000",
    )
    registry = tmp_path / "live"
    _ = endpoint.write_registration(registry)
    client = OmoLiveClient((registry,))

    try:
        first = client.send_to_session(
            session_id,
            "resume",
            request_id="same-request-id",
        )
        replay = client.send_to_session(
            session_id,
            "resume",
            request_id="same-request-id",
        )

        assert first.accepted is True
        assert first.replayed is False
        assert replay.accepted is True
        assert replay.replayed is True
        assert endpoint.deliveries == [("same-request-id", "resume")]
    finally:
        client.close()
        endpoint.close()
