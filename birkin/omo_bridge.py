"""Discovery and installation helpers for Birkin's OMO live bridge."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .omo_rpc import JsonObject

PROTOCOL = 1
MAX_RESPONSE_BYTES = 65_536
DEFAULT_TIMEOUT = 2.0
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})


@dataclass(frozen=True, slots=True)
class LiveSessionRegistration:
    """One capability-protected endpoint published by a live OMO session."""

    session_id: str
    host: str
    port: int
    token: str
    path: Path


def default_registry_roots() -> tuple[Path, ...]:
    """Return live-session registry roots without scanning transcripts."""
    configured = os.environ.get("BIRKIN_OMO_LIVE_DIR")
    if configured:
        return (Path(configured).expanduser(),)

    home = Path.home()
    roots = [
        home / ".omo" / "agent" / "birkin" / "live-sessions",
        home / ".senpi" / "agent" / "birkin" / "live-sessions",
    ]
    agent_dir = os.environ.get("OMO_CODING_AGENT_DIR")
    if agent_dir:
        roots.insert(0, Path(agent_dir).expanduser() / "birkin" / "live-sessions")
    for base_name in (".omo", ".senpi"):
        profiles = home / base_name / "profiles"
        if profiles.is_dir():
            roots.extend(
                profile / "agent" / "birkin" / "live-sessions"
                for profile in profiles.iterdir()
                if profile.is_dir()
            )
    return tuple(dict.fromkeys(roots))


def load_registrations(
    roots: Sequence[Path],
) -> tuple[LiveSessionRegistration, ...]:
    """Parse valid loopback registration records from trusted roots."""
    registrations: list[LiveSessionRegistration] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.glob("*.json"):
            registration = _read_registration(path)
            if registration is not None:
                registrations.append(registration)
    return tuple(registrations)


def bridge_extension_path() -> Path:
    """Return the packaged OMO extension entrypoint."""
    return Path(__file__).with_name("omo_live_bridge.mjs")


def install_bridge_extension(agent_dir: Path | None = None) -> Path:
    """Atomically install the bridge without editing OMO settings."""
    selected_agent_dir = agent_dir
    if selected_agent_dir is None:
        configured = os.environ.get("OMO_CODING_AGENT_DIR")
        selected_agent_dir = (
            Path(configured).expanduser()
            if configured
            else Path.home() / ".omo" / "agent"
        )
    source = bridge_extension_path()
    destination = selected_agent_dir / "extensions" / "birkin-omo-live-bridge.mjs"
    payload = source.read_bytes()
    if destination.is_file() and destination.read_bytes() == payload:
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            _ = handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        _ = temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _read_registration(path: Path) -> LiveSessionRegistration | None:
    try:
        decoded = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    payload = cast(JsonObject, decoded)
    session_id = payload.get("session_id")
    host = payload.get("host")
    port = payload.get("port")
    token = payload.get("token")
    if (
        payload.get("protocol") != PROTOCOL
        or not isinstance(session_id, str)
        or not session_id
        or not isinstance(host, str)
        or host not in LOOPBACK_HOSTS
        or not isinstance(port, int)
        or isinstance(port, bool)
        or not 1 <= port <= 65_535
        or not isinstance(token, str)
        or len(token) < 32
    ):
        return None
    return LiveSessionRegistration(session_id, host, port, token, path)
