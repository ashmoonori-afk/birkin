from __future__ import annotations

import threading
from types import TracebackType
from typing import cast, final

from birkin.workspace.terminal_session import TerminalSessions


def install_attempt_lock(
    sessions: TerminalSessions,
    terminal_id: str,
    attempting: threading.Event,
) -> None:
    stored = cast(dict[str, object], getattr(sessions, "_sessions"))
    setattr(stored[terminal_id], "emit_lock", AttemptSignalingRLock(attempting))


@final
class AttemptSignalingRLock:
    def __init__(self, attempting: threading.Event) -> None:
        self._lock = threading.RLock()
        self._state = threading.Lock()
        self._attempting = attempting
        self._owner: int | None = None
        self._depth = 0

    def __enter__(self) -> AttemptSignalingRLock:
        identity = threading.get_ident()
        with self._state:
            contended = self._owner is not None and self._owner != identity
        if contended:
            self._attempting.set()
        _ = self._lock.acquire()
        with self._state:
            self._owner = identity
            self._depth += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        with self._state:
            self._depth -= 1
            if self._depth == 0:
                self._owner = None
        self._lock.release()
