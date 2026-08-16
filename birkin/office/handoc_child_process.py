"""Cancellation and bounded I/O primitives for HanDoc child processes."""

from __future__ import annotations

import errno
import os
import signal
from collections.abc import Callable, Sequence
from threading import Lock
from typing import BinaryIO, NoReturn, Protocol, final

MAX_CAPTURE_BYTES = 64 * 1024


@final
class Cancellation:
    """Callback cancellation token that does not rely on timing or polling."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._cancelled = False
        self._callbacks: set[Callable[[], None]] = set()

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def cancel(self) -> None:
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
            callbacks = tuple(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            callback()

    def register(self, callback: Callable[[], None]) -> Callable[[], None]:
        with self._lock:
            if self._cancelled:
                run_now = True
            else:
                self._callbacks.add(callback)
                run_now = False
        if run_now:
            callback()

        def unregister() -> None:
            with self._lock:
                self._callbacks.discard(callback)

        return unregister


class ChildProcess(Protocol):
    pid: int
    returncode: int | None

    def communicate(
        self,
        input: str | None = None,
        timeout: float | None = None,
    ) -> tuple[object, object]: ...

    def kill(self) -> None: ...


class ProcessFactory(Protocol):
    def __call__(self, args: Sequence[str], **kwargs: object) -> ChildProcess: ...


def default_process_factory() -> ProcessFactory:
    def unavailable(args: Sequence[str], **kwargs: object) -> NoReturn:
        _ = args, kwargs
        raise OSError(errno.ENOSYS, "HanDoc process creation is unavailable")

    return unavailable


def kill_process_tree(process: ChildProcess) -> None:
    if os.name == "posix":
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    try:
        process.kill()
    except OSError:
        pass


def drain_bounded(
    source: BinaryIO,
    capture: BinaryIO,
    errors: list[OSError],
) -> None:
    remaining = MAX_CAPTURE_BYTES
    try:
        while chunk := source.read(64 * 1024):
            if remaining:
                selected = chunk[:remaining]
                _ = capture.write(selected)
                remaining -= len(selected)
        capture.flush()
    except OSError as exc:
        errors.append(exc)
    finally:
        source.close()


def read_capture(capture: BinaryIO) -> str:
    _ = capture.seek(0)
    return capture.read(MAX_CAPTURE_BYTES).decode("utf-8", errors="replace")
