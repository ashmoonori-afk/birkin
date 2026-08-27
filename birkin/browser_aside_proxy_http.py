"""HTTP framing helpers for the Browser filtering proxy."""

from __future__ import annotations

import socket
import select

MAX_PROXY_HEADER_BYTES = 65_536


def send_auth_required(client: socket.socket) -> None:
    client.sendall(
        b"HTTP/1.1 407 Proxy Authentication Required\r\n"
        + b'Proxy-Authenticate: Basic realm="birkin-browser"\r\n'
        + b"Content-Length: 0\r\n"
        + b"Connection: close\r\n\r\n"
    )


def read_request_header(
    client: socket.socket,
    wakeup: socket.socket | None = None,
) -> tuple[bytes, bytes]:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        if wakeup is not None:
            readable, _, _ = select.select(
                (client, wakeup),
                (),
                (),
                client.gettimeout(),
            )
            if wakeup in readable:
                raise OSError("proxy is closing")
            if not readable:
                raise TimeoutError("proxy request header timed out")
        chunk = client.recv(8_192)
        if not chunk:
            raise ValueError("proxy request ended before headers")
        data.extend(chunk)
        if len(data) > MAX_PROXY_HEADER_BYTES:
            raise ValueError("proxy request headers are too large")
    header, remainder = bytes(data).split(b"\r\n\r\n", 1)
    return header, remainder


def parse_request_header(
    header: bytes,
) -> tuple[tuple[str, str, str], list[bytes]]:
    lines = header.split(b"\r\n")
    parts = lines[0].decode("ascii").split(" ")
    if len(parts) != 3 or any(b"\x00" in line for line in lines):
        raise ValueError("invalid proxy request")
    return (parts[0].upper(), parts[1], parts[2]), lines[1:]


def send_denial(client: socket.socket) -> None:
    try:
        client.sendall(
            b"HTTP/1.1 403 Forbidden\r\n"
            + b"Content-Length: 0\r\n"
            + b"Connection: close\r\n\r\n"
        )
    except OSError:
        return
