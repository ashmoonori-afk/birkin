from __future__ import annotations

import http.client
import threading
from http.server import BaseHTTPRequestHandler

from birkin.web import server as web_server


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

        def log_message(self, *_args: object) -> None:
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
