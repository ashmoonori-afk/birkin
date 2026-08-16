"""Loopback filtering proxy that pins Chromium to policy-vetted peers."""

from __future__ import annotations

import base64
import secrets
import select
import socket
from threading import BoundedSemaphore, Event, Lock, Thread, current_thread
from typing import cast, final
from urllib.parse import urlsplit

from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_policy import BrowserEgressPolicy

MAX_PROXY_HEADER_BYTES = 65_536
MAX_PROXY_CONNECTIONS = 32
PROXY_IO_TIMEOUT_SECONDS = 30


@final
class BrowserFilteringProxy:
    def __init__(self, policy: BrowserEgressPolicy) -> None:
        self._policy = policy
        self._username = "birkin"
        self._password = secrets.token_urlsafe(24)
        self._listener = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM,
        )
        self._listener.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            0,
        )
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(MAX_PROXY_CONNECTIONS)
        address = cast(tuple[str, int], self._listener.getsockname())
        self._port = int(address[1])
        self._stop = Event()
        self._slots = BoundedSemaphore(MAX_PROXY_CONNECTIONS)
        self._connections: set[socket.socket] = set()
        self._workers: set[Thread] = set()
        self._lock = Lock()
        self._thread = Thread(
            target=self._accept_loop,
            name="birkin-browser-proxy",
            daemon=True,
        )

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    @property
    def credentials(self) -> tuple[str, str]:
        return self._username, self._password

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        try:
            self._listener.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._listener.close()
        with self._lock:
            connections = tuple(self._connections)
        for connection in connections:
            connection.close()
        self._thread.join(timeout=5)
        with self._lock:
            workers = tuple(self._workers)
        for worker in workers:
            worker.join(timeout=5)
        if self._thread.is_alive() or any(
            worker.is_alive() for worker in workers
        ):
            raise BrowserAsideError(
                "browser_proxy_cleanup_failed",
                "Browser network proxy cleanup failed.",
                500,
            )

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                accepted = cast(
                    tuple[socket.socket, tuple[str, int]],
                    self._listener.accept(),
                )
                client, _client_address = accepted
            except OSError:
                return
            if not self._slots.acquire(blocking=False):
                client.close()
                continue
            worker = Thread(
                target=self._serve,
                args=(client,),
                name="birkin-browser-proxy-client",
                daemon=True,
            )
            with self._lock:
                self._connections.add(client)
                self._workers.add(worker)
            worker.start()

    def _serve(self, client: socket.socket) -> None:
        client.settimeout(PROXY_IO_TIMEOUT_SECONDS)
        try:
            self._handle(client)
        finally:
            client.close()
            with self._lock:
                self._connections.discard(client)
                self._workers.discard(current_thread())
            self._slots.release()

    def _handle(self, client: socket.socket) -> None:
        try:
            header, remainder = self._request_header(client)
            request_line, headers = self._parse_header(header)
            if not self._authorized(headers):
                self._auth_required(client)
                return
            if any(line.lower().startswith(b"upgrade:") for line in headers):
                raise BrowserAsideError("external_protocol_denied",
                                        "Protocol upgrades are disabled.", 403)
            method, target, version = request_line
            if method == "CONNECT":
                upstream = self._connect(f"https://{target}/")
                with upstream:
                    client.sendall(
                        b"HTTP/1.1 200 Connection Established\r\n\r\n"
                    )
                    if remainder:
                        upstream.sendall(remainder)
                    self._relay(client, upstream)
                return
            parsed = urlsplit(target)
            if parsed.scheme not in {"http", "https"}:
                raise BrowserAsideError(
                    "unsupported_scheme",
                    "Only http and https navigation is allowed.",
                    400,
                )
            upstream = self._connect(target)
            with upstream:
                path = parsed.path or "/"
                if parsed.query:
                    path = f"{path}?{parsed.query}"
                filtered = [
                    line
                    for line in headers
                    if not line.lower().startswith(
                        (
                            b"connection:",
                            b"proxy-connection:",
                            b"proxy-authorization:",
                        )
                    )
                ]
                upstream.sendall(
                    f"{method} {path} {version}\r\n".encode("ascii")
                    + b"\r\n".join(filtered)
                    + b"\r\nConnection: close\r\n\r\n"
                    + remainder
                )
                self._relay_response(client, upstream)
        except (BrowserAsideError, OSError, ValueError):
            self._deny(client)

    def _connect(self, url: str) -> socket.socket:
        destination, pinned_peer = self._policy.connect(url)
        upstream = socket.create_connection(
            (pinned_peer, destination.port),
            timeout=PROXY_IO_TIMEOUT_SECONDS,
        )
        peer_address = cast(tuple[str, int], upstream.getpeername())
        actual_peer = peer_address[0]
        try:
            self._policy.verify_peer(url, actual_peer)
        except BrowserAsideError:
            upstream.close()
            raise
        return upstream

    def _authorized(self, headers: list[bytes]) -> bool:
        value = next(
            (
                line.split(b":", 1)[1].strip()
                for line in headers
                if line.lower().startswith(b"proxy-authorization:")
            ),
            b"",
        )
        expected = b"Basic " + base64.b64encode(
            f"{self._username}:{self._password}".encode()
        )
        return secrets.compare_digest(value, expected)

    @staticmethod
    def _auth_required(client: socket.socket) -> None:
        client.sendall(
            b"HTTP/1.1 407 Proxy Authentication Required\r\n"
            + b'Proxy-Authenticate: Basic realm="birkin-browser"\r\n'
            + b"Content-Length: 0\r\n"
            + b"Connection: close\r\n\r\n"
        )

    @staticmethod
    def _request_header(
        client: socket.socket,
    ) -> tuple[bytes, bytes]:
        data = bytearray()
        while b"\r\n\r\n" not in data:
            chunk = client.recv(8_192)
            if not chunk:
                raise ValueError("proxy request ended before headers")
            data.extend(chunk)
            if len(data) > MAX_PROXY_HEADER_BYTES:
                raise ValueError("proxy request headers are too large")
        header, remainder = bytes(data).split(b"\r\n\r\n", 1)
        return header, remainder

    @staticmethod
    def _parse_header(
        header: bytes,
    ) -> tuple[tuple[str, str, str], list[bytes]]:
        lines = header.split(b"\r\n")
        parts = lines[0].decode("ascii").split(" ")
        if len(parts) != 3 or any(b"\x00" in line for line in lines):
            raise ValueError("invalid proxy request")
        return (parts[0].upper(), parts[1], parts[2]), lines[1:]

    @staticmethod
    def _relay(left: socket.socket, right: socket.socket) -> None:
        sockets = (left, right)
        while True:
            readable, _, _ = select.select(
                sockets,
                (),
                (),
                PROXY_IO_TIMEOUT_SECONDS,
            )
            if not readable:
                return
            for source in readable:
                data = source.recv(65_536)
                if not data:
                    return
                target = right if source is left else left
                target.sendall(data)

    @staticmethod
    def _relay_response(
        client: socket.socket,
        upstream: socket.socket,
    ) -> None:
        while data := upstream.recv(65_536):
            client.sendall(data)

    @staticmethod
    def _deny(client: socket.socket) -> None:
        try:
            client.sendall(
                b"HTTP/1.1 403 Forbidden\r\n"
                + b"Content-Length: 0\r\n"
                + b"Connection: close\r\n\r\n"
            )
        except OSError:
            return
