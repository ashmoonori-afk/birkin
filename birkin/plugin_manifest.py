"""Strict manifest contract for installable Birkin plugin bundles."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping

from .sandbox import NetworkPolicy, SandboxConfigError, SandboxPolicy


class ManifestError(ValueError):
    """A plugin manifest is malformed or ambiguous."""


class PluginKind(str, Enum):
    SKILL = "skill"
    AGENT = "agent"


_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
_REQUIRED = {"name", "version", "kinds", "entry_points", "required_permissions"}
_ALLOWED = _REQUIRED | {"unsigned_allowed"}
_POLICY_FIELDS = {"network", "network_allowlist", "env_allowlist", "write_paths"}


@dataclass(frozen=True)
class PluginManifest:
    name: str
    version: str
    kinds: tuple[PluginKind, ...]
    entry_points: Mapping[PluginKind, tuple[str, ...]]
    permissions: SandboxPolicy
    unsigned_allowed: bool = False

    @property
    def requires_confirmation(self) -> bool:
        policy = self.permissions
        return bool(
            PluginKind.AGENT in self.kinds
            or policy.network is not NetworkPolicy.OFF
            or policy.network_allowlist
            or policy.env_allowlist
            or policy.write_paths
        )

    def permission_record(self) -> dict[str, object]:
        return {
            "network": self.permissions.network.value,
            "network_allowlist": list(self.permissions.network_allowlist),
            "env_allowlist": list(self.permissions.env_allowlist),
            "write_paths": list(self.permissions.write_paths),
        }


def _strings(raw: object, label: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw or not all(
        isinstance(item, str) and item for item in raw
    ):
        raise ManifestError(f"{label} must be a non-empty string array")
    return tuple(raw)


def _entry_point(raw: str) -> str:
    file_part, separator, symbol = raw.partition(":")
    path = PurePosixPath(file_part.replace("\\", "/"))
    if (
        not file_part
        or path.is_absolute()
        or ".." in path.parts
        or (separator and not symbol)
        or (not separator and ":" in raw)
    ):
        raise ManifestError(f"invalid entry point: {raw!r}")
    return raw


def _permissions(raw: object) -> SandboxPolicy:
    if not isinstance(raw, dict) or set(raw) != _POLICY_FIELDS:
        raise ManifestError(
            "required_permissions must contain exactly network, "
            "network_allowlist, env_allowlist, write_paths"
        )
    arrays: dict[str, tuple[str, ...]] = {}
    for field in ("network_allowlist", "env_allowlist", "write_paths"):
        value = raw[field]
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise ManifestError(f"required_permissions.{field} must be a string array")
        arrays[field] = tuple(value)
    try:
        return SandboxPolicy(
            network=NetworkPolicy(raw["network"]),
            network_allowlist=arrays["network_allowlist"],
            env_allowlist=arrays["env_allowlist"],
            write_paths=arrays["write_paths"],
        )
    except (ValueError, SandboxConfigError) as exc:
        raise ManifestError(f"invalid required_permissions: {exc}") from exc


def load_manifest(path: Path) -> PluginManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError("manifest must be an object")
    missing, unknown = _REQUIRED - set(raw), set(raw) - _ALLOWED
    if missing or unknown:
        raise ManifestError(
            f"manifest fields invalid (missing={sorted(missing)}, unknown={sorted(unknown)})"
        )
    name, version = raw["name"], raw["version"]
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ManifestError("name must be lowercase kebab-case")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ManifestError("version must be an exact semantic version")
    if not isinstance(raw["kinds"], list) or not raw["kinds"]:
        raise ManifestError("kinds must be a non-empty array")
    unsupported = sorted(
        {
            str(item)
            for item in raw["kinds"]
            if item in {"hook", "mcp_server"}
        }
    )
    if unsupported:
        raise ManifestError(
            f"plugin kind {unsupported[0]!r} is not activatable; "
            "supported kinds are skill and agent"
        )
    try:
        kinds = tuple(PluginKind(item) for item in raw["kinds"])
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"invalid kind: {exc}") from exc
    if len(set(kinds)) != len(kinds):
        raise ManifestError("kinds must not contain duplicates")
    points_raw = raw["entry_points"]
    if not isinstance(points_raw, dict):
        raise ManifestError("entry_points must be an object")
    points: dict[PluginKind, tuple[str, ...]] = {}
    for key, value in points_raw.items():
        try:
            kind = PluginKind(key)
        except (TypeError, ValueError) as exc:
            raise ManifestError(f"invalid entry point kind: {key!r}") from exc
        points[kind] = tuple(_entry_point(item) for item in _strings(value, f"entry_points.{key}"))
    if set(points) != set(kinds):
        raise ManifestError("entry_points must have exactly one entry for each declared kind")
    unsigned = raw.get("unsigned_allowed", False)
    if not isinstance(unsigned, bool):
        raise ManifestError("unsigned_allowed must be a boolean")
    return PluginManifest(
        name, version, kinds, MappingProxyType(points), _permissions(raw["required_permissions"]), unsigned
    )
