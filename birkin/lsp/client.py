"""A synchronous LSP client: one reader thread, bounded waits, no event loop.

asyncio is out of bounds in birkin by project decision, and it is not needed:
a language server is one child process on a pipe. A daemon thread drains
stdout, replies are matched by request id, and every wait carries a deadline.

That last part is the whole point. A language server that wedges -- and they
do, on a large workspace or a bad config -- must cost one edit its diagnostics,
never the agent's turn. Every path out of this module is bounded: a request
that goes unanswered raises, a server that dies raises, and a missing binary
raises at construction instead of on first use.
"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .protocol import LspError, encode, read_message

DEFAULT_TIMEOUT = 10.0


class LspClient:
    """One language-server process, driven synchronously."""

    def __init__(self, argv: list[str], *, cwd: Optional[Path] = None,
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        self.timeout = float(timeout)
        self._next_id = 0
        self._replies: dict[Any, dict[str, Any]] = {}
        self._diagnostics: dict[str, list[dict[str, Any]]] = {}
        self._arrived = threading.Condition()
        self._closed = False
        try:
            self._proc = subprocess.Popen(
                list(argv), cwd=str(cwd) if cwd else None,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL)
        except OSError as exc:
            # A missing language server is the common case on a fresh machine.
            # Failing here, by name, beats failing later inside an edit.
            raise LspError(f"could not start {argv[0]!r}: {exc}")
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()

    # -- the reader thread -------------------------------------------------

    def _drain(self) -> None:
        try:
            while True:
                message = read_message(self._proc.stdout)
                if message is None:
                    break
                self._deliver(message)
        except (LspError, OSError, ValueError):
            pass                      # a broken stream ends the thread, not the turn
        finally:
            with self._arrived:
                self._closed = True
                self._arrived.notify_all()

    def _deliver(self, message: dict[str, Any]) -> None:
        with self._arrived:
            if "id" in message and ("result" in message or "error" in message):
                self._replies[message["id"]] = message
            elif message.get("method") == "textDocument/publishDiagnostics":
                params = message.get("params") or {}
                uri = str(params.get("uri") or "")
                found = params.get("diagnostics")
                self._diagnostics[uri] = found if isinstance(found, list) else []
            self._arrived.notify_all()

    # -- sending -----------------------------------------------------------

    def _write(self, payload: dict[str, Any]) -> None:
        try:
            self._proc.stdin.write(encode(payload))
            self._proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise LspError(f"language server is not accepting input: {exc}")

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict[str, Any],
                timeout: Optional[float] = None) -> Any:
        """Send a request and wait for its reply, bounded."""
        self._next_id += 1
        request_id = self._next_id
        self._write({"jsonrpc": "2.0", "id": request_id,
                     "method": method, "params": params})
        deadline = time.monotonic() + float(timeout or self.timeout)
        with self._arrived:
            while request_id not in self._replies:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LspError(f"{method!r} went unanswered")
                if self._closed:
                    raise LspError(
                        f"language server exited before answering {method!r}")
                self._arrived.wait(min(remaining, 0.25))
            reply = self._replies.pop(request_id)
        if "error" in reply:
            raise LspError(f"{method!r} failed: {reply['error']}")
        return reply.get("result")

    # -- diagnostics -------------------------------------------------------

    def diagnostics_for(self, path: Path, text: str,
                        language_id: str = "python",
                        timeout: Optional[float] = None) -> list[dict[str, Any]]:
        """Open ``path`` and return what the server publishes about it.

        A server with nothing to say may publish an empty list or say nothing
        at all, and the two are indistinguishable from here. Both come back as
        "no diagnostics" once the wait is spent -- a silent server must not
        hold up the edit that asked.
        """
        uri = Path(path).resolve().as_uri()
        with self._arrived:
            # Forget what this URI said last time. Diagnostics are cached
            # by URI, so a second open -- the after-edit one -- would
            # otherwise return the BEFORE-edit answer instantly and never
            # wait for the server to republish. The delta would then
            # always be empty, which is exactly the shape of "no problems
            # found" and therefore invisible.
            self._diagnostics.pop(uri, None)
        self.notify("textDocument/didOpen", {"textDocument": {
            "uri": uri, "languageId": language_id, "version": 1,
            "text": text}})
        deadline = time.monotonic() + float(timeout or self.timeout)
        with self._arrived:
            while uri not in self._diagnostics:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._closed:
                    return []
                self._arrived.wait(min(remaining, 0.25))
            return list(self._diagnostics[uri])

    # -- lifecycle ---------------------------------------------------------

    @property
    def returncode(self) -> Optional[int]:
        return self._proc.poll()

    def close(self) -> None:
        """Shut the server down politely, then make sure it is actually gone."""
        try:
            self.request("shutdown", {}, timeout=2.0)
        except LspError:
            pass
        try:
            self.notify("exit", {})
        except LspError:
            pass
        for stream in (self._proc.stdin, self._proc.stdout):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
        try:
            self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass

    def __enter__(self) -> "LspClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()
