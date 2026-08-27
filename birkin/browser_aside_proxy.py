"""Loopback filtering proxy that pins Chromium to policy-vetted peers."""

from __future__ import annotations

import base64
import secrets
import select
import socket
from queue import Empty, SimpleQueue
from threading import BoundedSemaphore, Event, Lock, Thread, current_thread
from typing import cast, final
from urllib.parse import urlsplit

from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_policy import BrowserEgressPolicy
from birkin.browser_aside_proxy_http import (
    parse_request_header,
    read_request_header,
    send_auth_required,
    send_denial,
)

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
        self._wake_reader, self._wake_writer = socket.socketpair()
        address = cast(tuple[str, int], self._listener.getsockname())
        self._port = int(address[1])
        self._stop = Event()
        self._slots = BoundedSemaphore(MAX_PROXY_CONNECTIONS)
        self._connections: set[socket.socket] = set()
        self._workers: set[Thread] = set()
        self._denials: SimpleQueue[BrowserAsideError] = SimpleQueue()
        self._lock = Lock()
        self._started = False
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
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError("browser proxy is already closed")
            self._thread.start()
            self._started = True

    def close(self) -> None:
        self._stop.set()
        try:
            _ = self._wake_writer.send(b"\0")
        except OSError:
            pass
        try:
            self._listener.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._listener.close()
        with self._lock:
            started = self._started
        if started:
            self._thread.join(timeout=5)
        with self._lock:
            connections = tuple(self._connections)
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        with self._lock:
            workers = tuple(self._workers)
        for worker in workers:
            worker.join(timeout=5)
        self._wake_reader.close()
        self._wake_writer.close()
        if (started and self._thread.is_alive()) or any(
            worker.is_alive() for worker in workers
        ):
            raise BrowserAsideError(
                "browser_proxy_cleanup_failed",
                "Browser network proxy cleanup failed.",
                500,
            )

    def take_denial(self) -> BrowserAsideError | None:
        try:
            return self._denials.get_nowait()
        except Empty:
            return None

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
            header, remainder = read_request_header(
                client,
                self._wake_reader,
            )
            request_line, headers = parse_request_header(header)
            if not self._authorized(headers):
                send_auth_required(client)
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
                self._relay(client, upstream)
        except BrowserAsideError as exc:
            self._denials.put(exc)
            send_denial(client)
        except (OSError, ValueError):
            send_denial(client)

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

    def _relay(self, left: socket.socket, right: socket.socket) -> None:
        active = [left, right]
        while active:
            readable, _, _ = select.select(
                (*active, self._wake_reader),
                (),
                (),
                PROXY_IO_TIMEOUT_SECONDS,
            )
            if not readable:
                return
            if self._wake_reader in readable:
                return
            for source in readable:
                data = source.recv(65_536)
                target = right if source is left else left
                if not data:
                    active.remove(source)
                    try:
                        target.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                else:
                    target.sendall(data)
