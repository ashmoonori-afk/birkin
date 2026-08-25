"""Pinned project/team installation and resolution for plugin bundles."""

from __future__ import annotations

import json
import os
import shutil
import stat
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import cast

from .plugin_manifest import PluginManifest, load_manifest
from .plugin_signature import verify_bundle


class PluginInstallError(RuntimeError):
    """Base class for plugin installation failures."""


class InstallConfirmationRequired(PluginInstallError, PermissionError):
    """Non-read-only permissions were not confirmed."""


class VersionConflict(PluginInstallError):
    """A scope has an incompatible authoritative version pin."""


class Scope(str, Enum):
    PROJECT = "project"
    TEAM = "team"


@dataclass(frozen=True)
class Inspection:
    manifest: PluginManifest
    digest: str
    signature: str

    def machine_record(self) -> dict[str, object]:
        return {
            "name": self.manifest.name,
            "version": self.manifest.version,
            "kinds": [kind.value for kind in self.manifest.kinds],
            "permissions": self.manifest.permission_record(),
            "requires_confirmation": self.manifest.requires_confirmation,
            "signature": self.signature,
            "digest": self.digest,
        }


@dataclass(frozen=True)
class InstalledPlugin:
    name: str
    version: str
    scope: Scope
    path: Path
    digest: str
    signature: str


Disclosure = Callable[[Inspection], None]


def plugin_trust_policy(
    config: Mapping[str, object],
) -> tuple[dict[str, bytes], bool]:
    raw = config.get("plugins")
    if raw is None:
        return {}, False
    if not isinstance(raw, Mapping):
        raise PluginInstallError("plugins configuration must be a table")
    trusted = raw.get("trusted_keys", {})
    if not isinstance(trusted, Mapping):
        raise PluginInstallError("plugins.trusted_keys must be a table")
    keys: dict[str, bytes] = {}
    for key_id, encoded in trusted.items():
        if not isinstance(key_id, str) or not key_id:
            raise PluginInstallError("plugin trusted key ids must be non-empty strings")
        if not isinstance(encoded, str):
            raise PluginInstallError(
                f"plugins.trusted_keys.{key_id} must be hex text"
            )
        try:
            keys[key_id] = bytes.fromhex(encoded)
        except ValueError as exc:
            raise PluginInstallError(
                f"plugins.trusted_keys.{key_id} must be valid hex"
            ) from exc
        if not keys[key_id]:
            raise PluginInstallError(
                f"plugins.trusted_keys.{key_id} must not be empty"
            )
    allow_unsigned = raw.get("allow_unsigned", False)
    if not isinstance(allow_unsigned, bool):
        raise PluginInstallError("plugins.allow_unsigned must be a boolean")
    return keys, allow_unsigned


def _contained_bundle_dir(
    root: Path,
    name: str,
    version: str,
    record: Mapping[str, object],
) -> Path:
    raw = record.get("path")
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise PluginInstallError("installed plugin path is malformed")
    relative = PurePosixPath(raw)
    expected_parts = ("bundles", name, version)
    if relative.is_absolute() or relative.parts != expected_parts:
        raise PluginInstallError("installed plugin path is outside the registry")
    candidate = root.joinpath(*relative.parts)
    current = root
    try:
        for part in relative.parts:
            current = current / part
            metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise PluginInstallError(
                    f"installed plugin path contains a symbolic link: {raw}"
                )
    except FileNotFoundError as exc:
        raise PluginInstallError(f"installed plugin path does not exist: {raw}") from exc
    expected = root / "bundles" / name / version
    candidate_stat = candidate.stat()
    expected_stat = expected.stat()
    if (candidate_stat.st_dev, candidate_stat.st_ino) != (
        expected_stat.st_dev,
        expected_stat.st_ino,
    ):
        raise PluginInstallError("installed plugin path identity mismatch")
    if not candidate.is_dir():
        raise PluginInstallError("installed plugin path is not a directory")
    return candidate


class PluginInstaller:
    def __init__(self, project_root: Path, team_root: Path,
                 trusted_keys: Mapping[str, bytes] | None = None, *,
                 allow_unsigned: bool = False):
        self.project_root = project_root
        self.team_root = team_root
        self.trusted_keys = dict(trusted_keys or {})
        self.allow_unsigned = allow_unsigned

    def _root(self, scope: Scope) -> Path:
        if scope is Scope.PROJECT:
            return self.project_root
        if scope is Scope.TEAM:
            return self.team_root
        raise AssertionError(f"unhandled plugin scope: {scope}")

    def inspect(self, source: Path) -> Inspection:
        manifest = load_manifest(source / "birkin-plugin.json")
        for kind, entries in manifest.entry_points.items():
            for entry in entries:
                file_part = entry.partition(":")[0]
                if not (source / file_part).exists():
                    raise PluginInstallError(
                        f"missing {kind.value} entry point: {entry}"
                    )
        digest, signature = verify_bundle(
            source, self.trusted_keys, allow_missing=self.allow_unsigned
        )
        return Inspection(manifest, digest, signature)

    def install(self, source: Path, scope: Scope, version: str, *,
                confirmed: bool = False, upgrade: bool = False,
                disclose: Disclosure | None = None) -> InstalledPlugin:
        inspection = self.inspect(source)
        manifest = inspection.manifest
        if manifest.version != version:
            raise VersionConflict(
                f"requested exact version {version}, bundle is {manifest.version}"
            )
        if disclose is not None:
            disclose(inspection)
        if manifest.requires_confirmation and not confirmed:
            raise InstallConfirmationRequired(
                "bundle permissions require explicit confirmation"
            )
        root = self._root(scope)
        lock = self._read_lock(root, scope)
        bundles = cast(dict[str, object], lock["bundles"])
        current = bundles.get(manifest.name)
        if isinstance(current, dict) and current.get("version") != version and not upgrade:
            raise VersionConflict(
                f"{scope.value} scope pins {current.get('version')}; use --upgrade"
            )
        destination = root / "bundles" / manifest.name / version
        old: Path | None = None
        if isinstance(current, dict) and current.get("version") != version:
            old = _contained_bundle_dir(
                root,
                manifest.name,
                str(current.get("version", "")),
                current,
            )
        if isinstance(current, dict) and current.get("version") == version:
            if current.get("digest") != inspection.digest:
                raise VersionConflict(
                    f"{scope.value} scope already pins different bytes for {version}"
                )
            return self._installed(manifest.name, current, scope, root)
        staging = destination.with_name(f".{version}.{uuid.uuid4().hex}.tmp")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(source, staging)
            staged_digest, staged_signature = verify_bundle(
                staging,
                self.trusted_keys,
                allow_missing=self.allow_unsigned,
            )
            if (
                staged_digest != inspection.digest
                or staged_signature != inspection.signature
            ):
                raise PluginInstallError(
                    "staging copy does not match the inspected plugin bundle"
                )
            if destination.exists():
                raise VersionConflict(f"destination already exists: {destination}")
            os.replace(staging, destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        if old is not None and old != destination:
            shutil.rmtree(old)
        relative = destination.relative_to(root).as_posix()
        bundles[manifest.name] = {
            "version": version,
            "digest": inspection.digest,
            "signature": inspection.signature,
            "path": relative,
            "kinds": [kind.value for kind in manifest.kinds],
        }
        self._write_lock(root, lock)
        return InstalledPlugin(
            manifest.name,
            version,
            scope,
            destination,
            inspection.digest,
            inspection.signature,
        )

    def resolved(self) -> tuple[InstalledPlugin, ...]:
        """Return effective pins; project records shadow team records by name."""
        effective: dict[str, InstalledPlugin] = {}
        for scope in (Scope.TEAM, Scope.PROJECT):
            root = self._root(scope)
            records = self._read_lock(root, scope)["bundles"]
            assert isinstance(records, dict)
            for name, record in records.items():
                if isinstance(name, str) and isinstance(record, dict):
                    effective[name] = self._installed(name, record, scope, root)
        return tuple(effective[name] for name in sorted(effective))

    def resolve(self, name: str, version: str | None = None) -> InstalledPlugin:
        for scope in (Scope.PROJECT, Scope.TEAM):
            root = self._root(scope)
            records = self._read_lock(root, scope)["bundles"]
            assert isinstance(records, dict)
            record = records.get(name)
            if not isinstance(record, dict):
                continue
            installed = self._installed(name, record, scope, root)
            if version is not None and installed.version != version:
                raise VersionConflict(
                    f"{scope.value} scope pins {installed.version}, not requested {version}"
                )
            return installed
        raise PluginInstallError(f"plugin is not installed: {name}")

    @staticmethod
    def _installed(name: str, record: dict[str, object], scope: Scope,
                   root: Path) -> InstalledPlugin:
        version = record.get("version")
        digest = record.get("digest")
        signature = record.get("signature")
        if not isinstance(version, str) or not isinstance(digest, str):
            raise PluginInstallError("installed plugin lock record is malformed")
        if not isinstance(signature, str):
            raise PluginInstallError(
                f"installed plugin {name}@{version} is unverified; "
                "reinstall with `birkin plugins install --upgrade`"
            )
        return InstalledPlugin(
            name,
            version,
            scope,
            _contained_bundle_dir(root, name, version, record),
            digest,
            signature,
        )

    @staticmethod
    def _read_lock(root: Path, scope: Scope) -> dict[str, object]:
        path = root / "registry.lock"
        if not path.is_file():
            return {"lock_version": 1, "scope": scope.value, "bundles": {}}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PluginInstallError(f"invalid lockfile {path}: {exc}") from exc
        if (not isinstance(raw, dict) or raw.get("lock_version") != 1
                or raw.get("scope") != scope.value
                or not isinstance(raw.get("bundles"), dict)):
            raise PluginInstallError(f"invalid lockfile structure: {path}")
        return raw

    @staticmethod
    def _write_lock(root: Path, lock: dict[str, object]) -> None:
        root.mkdir(parents=True, exist_ok=True)
        path = root / "registry.lock"
        temporary = path.with_suffix(f".lock.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
