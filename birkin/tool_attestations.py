"""Strict JSON persistence for user-owned tool effect attestations."""

from __future__ import annotations

import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any, final

from .tool_effects import EffectSnapshot, InspectGrant, PluginToolId

_MAX_BYTES = 1024 * 1024
_MAX_GRANTS = 4096
_TOP_KEYS = {"schema_version", "inspect_grants"}
_GRANT_KEYS = {
    "bundle_digest", "parallel_safe", "plugin", "plugin_version", "reason",
    "recorded_at", "tool",
}


class AttestationError(ValueError):
    """An attestation file or requested update violates the storage contract."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AttestationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid(message: str) -> EffectSnapshot:
    return EffectSnapshot("invalid", (), message)


def _grant_from_json(value: Any) -> InspectGrant:
    if not isinstance(value, dict) or set(value) != _GRANT_KEYS:
        raise AttestationError("inspect grant fields are not exact")
    string_fields = (
        "bundle_digest", "plugin", "plugin_version", "reason", "recorded_at", "tool")
    if any(not isinstance(value[field], str) for field in string_fields):
        raise AttestationError("inspect grant string field has invalid type")
    if type(value["parallel_safe"]) is not bool:
        raise AttestationError("parallel_safe must be a boolean")
    try:
        identity = PluginToolId(
            value["plugin"], value["plugin_version"], value["bundle_digest"], value["tool"])
        return InspectGrant(
            identity, value["parallel_safe"], value["reason"], value["recorded_at"])
    except ValueError as exc:
        raise AttestationError(str(exc)) from exc


def _grant_to_json(grant: InspectGrant) -> dict[str, Any]:
    identity = grant.identity
    return {
        "bundle_digest": identity.bundle_digest,
        "parallel_safe": grant.parallel_safe,
        "plugin": identity.plugin,
        "plugin_version": identity.version,
        "reason": grant.reason,
        "recorded_at": grant.recorded_at,
        "tool": identity.tool,
    }


def _sorted_grants(grants: tuple[InspectGrant, ...]) -> tuple[InspectGrant, ...]:
    if len(grants) > _MAX_GRANTS:
        raise AttestationError(f"inspect_grants exceeds {_MAX_GRANTS} entries")
    ordered = tuple(sorted(grants, key=lambda grant: (
        grant.identity.plugin, grant.identity.tool, grant.identity.version,
        grant.identity.bundle_digest,
    )))
    identities = [grant.identity for grant in ordered]
    if len(set(identities)) != len(identities):
        raise AttestationError("duplicate grant identity")
    return ordered


def _assert_regular(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise AttestationError("attestation path must be a regular file, not a symlink")


@final
class ToolAttestationStore:
    """Load and atomically update one strict tool-effects JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        home = Path(os.environ.get("BIRKIN_HOME", Path.home() / ".birkin"))
        self.path = Path(path) if path is not None else home / "tool-effects.json"

    def load(self) -> EffectSnapshot:
        try:
            _assert_regular(self.path)
            try:
                size = self.path.stat().st_size
            except FileNotFoundError:
                return EffectSnapshot("missing", ())
            if size > _MAX_BYTES:
                raise AttestationError("attestation file exceeds 1 MiB")
            raw = self.path.read_bytes()
            if len(raw) > _MAX_BYTES:
                raise AttestationError("attestation file exceeds 1 MiB")
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
            if not isinstance(value, dict) or set(value) != _TOP_KEYS:
                raise AttestationError("top-level fields are not exact")
            if type(value["schema_version"]) is not int or value["schema_version"] != 1:
                raise AttestationError("unknown schema version")
            entries = value["inspect_grants"]
            if not isinstance(entries, list):
                raise AttestationError("inspect_grants must be an array")
            if len(entries) > _MAX_GRANTS:
                raise AttestationError(f"inspect_grants exceeds {_MAX_GRANTS} entries")
            grants = _sorted_grants(tuple(_grant_from_json(entry) for entry in entries))
            return EffectSnapshot("valid", grants)
        except json.JSONDecodeError as exc:
            return _invalid(f"invalid JSON at line {exc.lineno} column {exc.colno}")
        except UnicodeDecodeError:
            return _invalid("attestation file is not valid UTF-8")
        except (AttestationError, OSError) as exc:
            return _invalid(str(exc))

    def write(self, grants: tuple[InspectGrant, ...]) -> None:
        current = self.load()
        if current.state == "invalid":
            raise AttestationError(current.diagnostic)
        ordered = _sorted_grants(tuple(grants))
        document = {
            "schema_version": 1,
            "inspect_grants": [_grant_to_json(grant) for grant in ordered],
        }
        data = (json.dumps(
            document, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        if len(data) > _MAX_BYTES:
            raise AttestationError("canonical attestation file exceeds 1 MiB")
        self._atomic_write(self.path, data)

    def reset(self) -> Path | None:
        _assert_regular(self.path)
        if not self.path.exists():
            self._atomic_write(self.path, self._empty_bytes())
            return None
        previous = self.path.read_bytes()
        backup = self.path.with_name(self.path.name + ".previous")
        self._atomic_write(backup, previous)
        self._atomic_write(self.path, self._empty_bytes())
        return backup

    @staticmethod
    def _empty_bytes() -> bytes:
        return (json.dumps(
            {"schema_version": 1, "inspect_grants": []},
            indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")

    @staticmethod
    def _atomic_write(destination: Path, data: bytes) -> None:
        _assert_regular(destination)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(destination.parent, 0o700)
        except OSError:
            pass
        temporary = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        except BaseException:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise
