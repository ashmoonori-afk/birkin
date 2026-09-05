"""Bounded announcements and authenticated helper ownership records."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import signal
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import TypeAlias, cast, final

Announce: TypeAlias = Callable[[str], None]


def emit(announce: Announce, record: dict[str, object]) -> None:
    """Announce one record as a single compact JSON line."""
    announce(json.dumps(record, separators=(",", ":")))


def write_line(line: str) -> None:
    """Default announce sink: one flushed line on stdout."""
    print(line, flush=True)


def connection_failure(exc: BaseException) -> dict[str, object]:
    """Describe a per-connection failure without secret-bearing payloads."""
    return {
        "event": "connection_failed",
        "error": f"{type(exc).__name__}: {exc}"[:200],
    }


def listening_record(
    *, transport: str, root: Path, session_id: str, instance_id: str,
    server_version: str, socket_path: Path, discovery_path: Path,
) -> dict[str, object]:
    record: dict[str, object] = {
        "event": "listening", "transport": transport, "pid": os.getpid(),
        "root": str(root), "session_id": session_id,
        "instance_id": instance_id, "server_version": server_version,
    }
    record[
        "socket_path" if transport == "uds" else "discovery_path"
    ] = str(socket_path if transport == "uds" else discovery_path)
    return record


def install_signal_handlers(stop: Callable[[], None]) -> Callable[[], None]:
    def handle(_signum: int, _frame: FrameType | None) -> None:
        stop()

    previous = [
        (number, signal.signal(number, handle))
        for number in (signal.SIGTERM, signal.SIGINT)
    ]

    def restore() -> None:
        for number, handler in previous:
            _ = signal.signal(number, handler)

    return restore


@final
class BridgeOwnershipLease:
    """Transferable, token-authenticated ownership of one helper instance.

    The PID is diagnostic metadata only. Retirement is performed by the helper
    itself after the bounded claim deadline; claimants never signal that PID.
    """

    def __init__(
        self,
        root: Path,
        *,
        instance_id: str,
        pid: int,
        token: str,
        now: Callable[[], float] = time.time,
        reclaim_seconds: float = 8.0,
    ) -> None:
        if not token or reclaim_seconds <= 0:
            raise ValueError("ownership token and positive reclaim window required")
        self._root = root / "native"
        self._root.mkdir(parents=True, exist_ok=True)
        self.record_path = self._root / "ownership.json"
        self.claim_path = self._root / "ownership.claim"
        self._instance_id = instance_id
        self._pid = pid
        self._token = token
        self._now = now
        self._reclaim_seconds = reclaim_seconds
        self._deadline = now() + reclaim_seconds
        self._owner_id = "initial"
        self._transport = ""
        self._endpoint = ""
        self._seen_signature: str | None = None
        self._authenticated_connection = False
        self._closed = False

    @property
    def owner_id(self) -> str:
        return self._owner_id

    @property
    def deadline(self) -> float:
        return self._deadline

    def publish(self, *, transport: str, endpoint: str) -> None:
        self._transport = transport
        self._endpoint = endpoint
        self._publish_record()

    def connection_authenticated(self) -> None:
        self._authenticated_connection = True

    def connection_closed(self) -> None:
        if self._authenticated_connection:
            self._authenticated_connection = False
            self._deadline = self._now() + self._reclaim_seconds
            self._publish_record()

    def check(self, *, now: float | None = None) -> bool:
        current = self._now() if now is None else now
        if self._authenticated_connection:
            return True
        claim = self._read_claim()
        if claim is not None:
            instance_id, owner_id, expires_at, signature = claim
            if (
                signature != self._seen_signature
                and instance_id == self._instance_id
                and expires_at > current
                and hmac.compare_digest(
                    signature,
                    self._signature(instance_id, owner_id, expires_at),
                )
            ):
                self._seen_signature = signature
                self._owner_id = owner_id
                self._deadline = expires_at
                self._publish_record()
        return current < self._deadline

    def wait_until_retired(self, stop: Callable[[], None]) -> None:
        """Wait on the lease deadline and ask the serving loop to stop.

        The bounded wait is the behavior under test; no PID observation or
        process reaping participates in ownership.
        """
        while not self._closed:
            if not self.check():
                stop()
                return
            remaining = max(0.01, min(0.25, self._deadline - self._now()))
            _ = threading.Event().wait(remaining)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _ = self.record_path.unlink(missing_ok=True)
        _ = self.claim_path.unlink(missing_ok=True)

    def _publish_record(self) -> None:
        _private_json(
            self.record_path,
            {
                "schema": 1,
                "instance_id": self._instance_id,
                "pid": self._pid,
                "owner_id": self._owner_id,
                "owner_token_sha256": hashlib.sha256(
                    self._token.encode("utf-8")
                ).hexdigest(),
                "lease_expires_at": self._deadline,
                "transport": self._transport,
                "endpoint": self._endpoint,
            },
        )

    def _read_claim(self) -> tuple[str, str, float, str] | None:
        try:
            value = cast(
                dict[str, object],
                json.loads(self.claim_path.read_text("utf-8")),
            )
            instance_id = value["instance_id"]
            owner_id = value["owner_id"]
            expires_at = value["expires_at"]
            signature = value["signature"]
            if (
                not isinstance(instance_id, str)
                or not isinstance(owner_id, str)
                or not isinstance(expires_at, (int, float))
                or not isinstance(signature, str)
            ):
                return None
            return instance_id, owner_id, float(expires_at), signature
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _signature(self, instance_id: str, owner_id: str, expires_at: float) -> str:
        payload = f"{instance_id}\n{owner_id}\n{expires_at:.6f}".encode("utf-8")
        return hmac.new(self._token.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def ownership_from_environment(
    root: Path,
    *,
    instance_id: str,
    pid: int,
) -> BridgeOwnershipLease | None:
    token = os.environ.get("BIRKIN_NATIVE_OWNER_TOKEN")
    if not token:
        return None
    return BridgeOwnershipLease(
        root, instance_id=instance_id, pid=pid, token=token
    )


def ownership_callbacks(
    ownership: BridgeOwnershipLease | None,
) -> tuple[Callable[[], None] | None, Callable[[], None] | None]:
    if ownership is None:
        return None, None
    return ownership.connection_authenticated, ownership.connection_closed


def start_ownership_monitor(
    ownership: BridgeOwnershipLease | None,
    *,
    transport: str,
    endpoint: str,
    stop: Callable[[], None],
) -> threading.Thread | None:
    if ownership is None:
        return None
    ownership.publish(transport=transport, endpoint=endpoint)
    thread = threading.Thread(
        target=ownership.wait_until_retired,
        args=(stop,),
        name="native-owner-lease",
        daemon=True,
    )
    thread.start()
    return thread


def _private_json(path: Path, value: dict[str, object]) -> None:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            _ = handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        _ = os.replace(temporary, path)
        if os.name != "nt":
            _ = os.chmod(path, 0o600)
    finally:
        _ = temporary.unlink(missing_ok=True)
