"""Token-scoped ownership for Telegram long-poll gateways."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

import psutil
from typing_extensions import override

from .. import config, store
from ..approval_execution_codec import JSONValue

_ACQUIRE_ATTEMPTS: Final = 3


class _JsonLoader(Protocol):
    def __call__(self, s: str) -> JSONValue: ...


_load_json: _JsonLoader = json.loads


@dataclass(frozen=True, slots=True)
class TelegramLeaseStatus:
    """Secret-free snapshot of one configured Telegram owner's state."""

    enabled: bool
    fingerprint: str | None
    owner_pid: int | None
    owner_alive: bool


@dataclass(frozen=True, slots=True)
class _OwnerRecord:
    pid: int
    process_started_at: float
    instance_id: str


@dataclass(frozen=True, slots=True)
class _TelegramSettings:
    enabled: bool
    token: str
    allowed_chat_count: int


@dataclass(frozen=True, slots=True)
class TelegramGatewayOwnedError(RuntimeError):
    """A live process already owns the configured Telegram bot."""

    owner_pid: int
    fingerprint: str
    path: Path

    @override
    def __str__(self) -> str:
        return (
            f"Telegram owner PID {self.owner_pid} already owns bot "
            f"{self.fingerprint} (lock {self.path})."
        )


class TelegramGatewayLeaseRaceError(RuntimeError):
    """The ownership record changed repeatedly during acquisition."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path: Path = path

    @override
    def __str__(self) -> str:
        return f"Telegram owner changed while acquiring the lease (lock {self.path})."


def _configured_token(cfg: dict[str, JSONValue]) -> str | None:
    telegram = _telegram_settings(cfg)
    if telegram is None or not telegram.enabled:
        return None
    token = (
        os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        or os.environ.get("BIRKIN_TELEGRAM_TOKEN", "").strip()
        or telegram.token
    )
    return token or None


def _telegram_settings(cfg: dict[str, JSONValue]) -> _TelegramSettings | None:
    channels = cfg.get("channels")
    if not isinstance(channels, dict):
        return None
    telegram = channels.get("telegram")
    if not isinstance(telegram, dict):
        return None
    allowed_chat_ids = telegram.get("allowed_chat_ids")
    return _TelegramSettings(
        enabled=telegram.get("enabled") is True,
        token=str(telegram.get("token", "")).strip(),
        allowed_chat_count=(
            len(allowed_chat_ids) if isinstance(allowed_chat_ids, list) else 0
        ),
    )


def _fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def _owner_path(token: str) -> Path:
    return (
        config.birkin_home() / "gateway-locks" / f"telegram-{_fingerprint(token)}.json"
    )


def _read_owner(path: Path) -> _OwnerRecord | None:
    try:
        value = _load_json(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(value, dict):
        return None
    pid = value.get("pid")
    process_started_at = value.get("process_started_at")
    instance_id = value.get("instance_id")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or not isinstance(process_started_at, int | float)
        or isinstance(process_started_at, bool)
        or not isinstance(instance_id, str)
        or not instance_id
    ):
        return None
    return _OwnerRecord(pid, float(process_started_at), instance_id)


def _owner_is_alive(owner: _OwnerRecord) -> bool:
    """True only while the recorded PID is still the process that claimed it.

    A PID alone is not an identity — the OS reuses it. The create_time recorded
    at acquire settles it whenever it is readable, so a PID inherited by an
    unrelated process (after a hard kill) reads as dead and the lock is
    reclaimed. When create_time is unreadable we cannot tell, so the owner
    stays "alive" and ``TelegramGatewayOwnedError`` names the lock path for the
    operator.
    """
    try:
        created = psutil.Process(owner.pid).create_time()
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
    except psutil.AccessDenied:
        return True
    return abs(created - owner.process_started_at) < 0.01


@dataclass(frozen=True, slots=True)
class TelegramGatewayLease:
    """Atomic process ownership released only by the instance that claimed it."""

    path: Path
    owner: _OwnerRecord
    fingerprint: str

    @classmethod
    def acquire_for_config(
        cls,
        cfg: dict[str, JSONValue],
    ) -> TelegramGatewayLease | None:
        token = _configured_token(cfg)
        if token is None:
            return None
        path = _owner_path(token)
        path.parent.mkdir(parents=True, exist_ok=True)
        owner = _OwnerRecord(
            pid=os.getpid(),
            process_started_at=psutil.Process().create_time(),
            instance_id=str(uuid.uuid4()),
        )
        payload = json.dumps(
            {
                "pid": owner.pid,
                "process_started_at": owner.process_started_at,
                "instance_id": owner.instance_id,
                "claimed_at": time.time(),
            },
            separators=(",", ":"),
        )
        unpublished_path = path.with_name(f".{path.name}.{owner.instance_id}.tmp")
        descriptor = os.open(
            unpublished_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                _ = handle.write(payload)
                _ = handle.write("\n")
            try:
                with store.file_lock(path.with_suffix(".guard")):
                    for _attempt in range(_ACQUIRE_ATTEMPTS):
                        try:
                            os.link(unpublished_path, path)
                        except FileExistsError:
                            existing = _read_owner(path)
                            if existing is None:
                                raise TelegramGatewayLeaseRaceError(path)
                            if _owner_is_alive(existing):
                                raise TelegramGatewayOwnedError(
                                    existing.pid,
                                    _fingerprint(token),
                                    path,
                                )
                            try:
                                path.unlink()
                            except FileNotFoundError:
                                continue
                        else:
                            return cls(path, owner, _fingerprint(token))
                    raise TelegramGatewayLeaseRaceError(path)
            except (store.FileLockTimeout, OSError) as exc:
                raise TelegramGatewayLeaseRaceError(path) from exc
        finally:
            unpublished_path.unlink(missing_ok=True)

    @classmethod
    def status_for_config(
        cls,
        cfg: dict[str, JSONValue],
    ) -> TelegramLeaseStatus:
        token = _configured_token(cfg)
        if token is None:
            return TelegramLeaseStatus(False, None, None, False)
        owner = _read_owner(_owner_path(token))
        return TelegramLeaseStatus(
            enabled=True,
            fingerprint=_fingerprint(token),
            owner_pid=owner.pid if owner is not None else None,
            owner_alive=owner is not None and _owner_is_alive(owner),
        )

    def release(self) -> None:
        try:
            with store.file_lock(self.path.with_suffix(".guard")):
                owner = _read_owner(self.path)
                if owner is None or owner.instance_id != self.owner.instance_id:
                    return
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    return
        except (store.FileLockTimeout, OSError) as exc:
            raise TelegramGatewayLeaseRaceError(self.path) from exc


def format_gateway_diagnostics(cfg: dict[str, JSONValue]) -> str:
    """Render secret-free ownership, channel, and OMO readiness details."""
    telegram = _telegram_settings(cfg)
    status = TelegramGatewayLease.status_for_config(cfg)
    allowed_count = telegram.allowed_chat_count if telegram is not None else 0
    if not status.enabled:
        owner = "Telegram owner: unavailable (channel disabled or token missing)"
        channel = "Telegram channel: disabled or missing token"
    elif status.owner_pid is None:
        owner = f"Telegram owner: unclaimed (bot {status.fingerprint})"
        channel = (
            f"Telegram channel: enabled; bot {status.fingerprint}; "
            f"allowed chats {allowed_count}"
        )
    else:
        state = "active" if status.owner_alive else "stale"
        owner = (
            f"Telegram owner: PID {status.owner_pid} ({state}; "
            f"bot {status.fingerprint})"
        )
        channel = (
            f"Telegram channel: enabled; bot {status.fingerprint}; "
            f"allowed chats {allowed_count}"
        )
    noun = "chat ID" if allowed_count == 1 else "chat IDs"
    omo = (
        f"OMO control: enabled for {allowed_count} configured Telegram {noun}"
        if status.enabled and allowed_count > 0
        else "OMO control: unavailable until Telegram and its allow-list are configured"
    )
    guidance = (
        "Conflict guidance: one process may own a Telegram bot token; "
        "gateways with different bot fingerprints may coexist."
    )
    return "\n".join((owner, channel, omo, guidance))
