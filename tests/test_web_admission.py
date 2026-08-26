from __future__ import annotations

import http.client
import socket
import threading
from http.server import BaseHTTPRequestHandler
from typing import final

from birkin.web import server as web_server


def test_saturated_rejection_drains_bounded_request_framing_before_503() -> None:
    events: list[str] = []
    framing = b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
    unread_body = b"rejected-application-work"

    @final
    class RejectedRequest:
        def __init__(self) -> None:
            self.buffer = framing + unread_body
            self._timeout: float | None = None
            self.response: bytes = b""

        def gettimeout(self) -> float | None:
            return self._timeout

        def settimeout(self, timeout: float | None) -> None:
            self._timeout = timeout
            events.append(f"timeout:{timeout}")

        def recv(self, size: int, flags: int = 0) -> bytes:
            events.append(
                f"{'peek' if flags & socket.MSG_PEEK else 'recv'}:{size}"
            )
            chunk = self.buffer[:size]
            if not flags & socket.MSG_PEEK:
                self.buffer = self.buffer[len(chunk) :]
            return chunk

        def sendall(self, payload: bytes) -> None:
            events.append("sendall")
            self.response = payload

        def shutdown(self, how: int) -> None:
            assert how == socket.SHUT_WR
            events.append("shutdown")

        def close(self) -> None:
            events.append("close")

    server = web_server.HTTPServer(
        ("127.0.0.1", 0),
        BaseHTTPRequestHandler,
    )
    request = RejectedRequest()
    try:
        for _index in range(web_server.MAX_PUBLIC_WORKERS):
            assert server._worker_slots.acquire(blocking=False)

        server.process_request(
            request,
            ("127.0.0.1", 0),
        )

        assert any(event.startswith("recv:") for event in events)
        assert events.index("sendall") > next(
            index
            for index, event in enumerate(events)
            if event.startswith("recv:")
        )
        assert request.buffer == unread_body
        assert request.response == (
            b"HTTP/1.1 503 Service Unavailable\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"Content-Length: 12\r\n"
            b"Connection: close\r\n\r\n"
            b"server busy\n"
        )
        assert not server._worker_slots.acquire(blocking=False)
    finally:
        for _index in range(web_server.MAX_PUBLIC_WORKERS):
            server._worker_slots.release()
        server.server_close()


def test_fifth_concurrent_web_request_gets_bounded_busy_response() -> None:
    release = threading.Event()
    condition = threading.Condition()
    started = 0

    class BlockingHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            nonlocal started
            with condition:
                started += 1
                condition.notify_all()
            release.wait()
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            del format, args
            return None

    server = web_server.HTTPServer(("127.0.0.1", 0), BlockingHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    port = int(server.server_address[1])

    def request() -> None:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request("GET", "/")
        response = connection.getresponse()
        _ = response.read()
        connection.close()

    clients = [
        threading.Thread(target=request, daemon=True)
        for _index in range(4)
    ]
    try:
        for client in clients:
            client.start()
        with condition:
            assert condition.wait_for(lambda: started == 4, timeout=2.0)

        fifth = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
        fifth.request("GET", "/")
        response = fifth.getresponse()
        body = response.read()
        fifth.close()

        assert response.status == 503
        assert body == b"server busy\n"
        assert server.request_queue_size == 16
        assert server.daemon_threads is True
    finally:
        release.set()
        for client in clients:
            client.join(timeout=2.0)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2.0)
