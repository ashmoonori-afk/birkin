"""Cancellable synchronous facade for model HTTP requests."""

from __future__ import annotations

import asyncio
import ssl
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from dataclasses import dataclass
from typing import Callable, Protocol

import httpx


class AbortSignal(Protocol):
    def is_set(self) -> bool: ...


class HTTPAborted(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_no_redirect(request: urllib.request.Request, *, timeout: float):
    """Open one HTTP(S) request without following redirects."""
    try:
        parsed = urlsplit(request.full_url)
        valid = (parsed.scheme in {"http", "https"} and parsed.hostname
                 and parsed.username is None and parsed.password is None)
    except (UnicodeError, ValueError):
        valid = False
    if not valid:
        raise urllib.error.URLError("unsupported request URL")
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


class HTTPTransportError(Exception):
    def __init__(self, message: str, *, response_started: bool):
        super().__init__(message)
        self.response_started = response_started


@dataclass(slots=True)
class HTTPResponse:
    status: int
    body: bytes

    def read(self) -> bytes:
        return self.body

    def __iter__(self):
        return iter(self.body.splitlines())

    def close(self) -> None:
        pass


async def _wait_abort(abort: AbortSignal) -> None:
    while not abort.is_set():
        await asyncio.sleep(0.01)


def post(
    url: str,
    *,
    headers: dict[str, str],
    data: bytes,
    timeout: float,
    abort: AbortSignal,
    on_line: Callable[[bytes], None] | None = None,
) -> HTTPResponse:
    """POST and return only after the request task and socket are closed."""
    if abort.is_set():
        raise HTTPAborted

    async def exchange() -> HTTPResponse:
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=0)
        async with httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            verify=ssl.create_default_context(),
        ) as client:
            response_started = False
            try:
                async with client.stream(
                    "POST", url, headers=headers, content=data,
                ) as response:
                    response_started = True
                    lines: list[bytes] = []
                    async for line in response.aiter_lines():
                        raw = line.encode("utf-8")
                        lines.append(raw)
                        if response.is_success and on_line is not None:
                            on_line(raw)
                    return HTTPResponse(response.status_code, b"\n".join(lines))
            except httpx.HTTPError as exc:
                raise HTTPTransportError(
                    str(exc), response_started=response_started) from exc

    async def run() -> HTTPResponse:
        request = asyncio.create_task(exchange())
        cancelled = asyncio.create_task(_wait_abort(abort))
        done, _ = await asyncio.wait(
            {request, cancelled}, return_when=asyncio.FIRST_COMPLETED)
        if cancelled in done:
            request.cancel()
            try:
                await request
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            raise HTTPAborted
        cancelled.cancel()
        try:
            await cancelled
        except asyncio.CancelledError:
            pass
        return await request

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run())

    results: list[HTTPResponse] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            results.append(asyncio.run(run()))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker, daemon=False)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return results[0]


def wait(seconds: float, abort: AbortSignal) -> None:
    """Abortible retry delay without assuming threading.Event."""
    deadline = time.monotonic() + seconds
    while True:
        if abort.is_set():
            raise HTTPAborted
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.01, remaining))
