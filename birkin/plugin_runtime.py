"""Activation adapters from installed bundles into Birkin's existing registries."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from .plugin_install import InstalledPlugin, PluginInstallError, PluginInstaller
from .plugin_manifest import PluginKind, load_manifest
from .plugin_signature import (
    SIGNATURE_FILE,
    SignatureError,
    bundle_digest_bytes,
    verify_bundle,
)
from .plugin_snapshot import (
    SnapshotActivationError,
    SnapshotActivation,
    SnapshotImportError,
    SnapshotTransactionError,
    load_snapshot_module,
)
from .tool_effects import ToolOrigin
from .tools._types import Tool


class PluginActivationError(SnapshotActivationError):
    """An installed plugin cannot safely satisfy its entry-point contract."""


def registry_roots(project: Path | None = None) -> tuple[Path, Path]:
    from .config import birkin_home
    workspace = (project or Path.cwd()).resolve()
    return workspace / ".birkin" / "registry", birkin_home() / "registry" / "team"


def _verified_plugins(
    project_root: Path,
    team_root: Path,
    trusted_keys: Mapping[str, bytes] | None = None,
    *,
    allow_unsigned: bool = False,
) -> tuple[InstalledPlugin, ...]:
    try:
        plugins = PluginInstaller(
            project_root,
            team_root,
            trusted_keys,
            allow_unsigned=allow_unsigned,
        ).resolved()
        for plugin in plugins:
            digest, signature = verify_bundle(
                plugin.path,
                trusted_keys or {},
                allow_missing=allow_unsigned,
            )
            if digest != plugin.digest or signature != plugin.signature:
                raise PluginActivationError(
                    "installed plugin verification does not match its lock record: "
                    f"{plugin.name}@{plugin.version}"
                )
            if signature == "unsigned-allowed" and not allow_unsigned:
                raise PluginActivationError(
                    f"unsigned plugin is disabled: {plugin.name}@{plugin.version}"
                )
        return plugins
    except (PluginInstallError, SignatureError) as exc:
        raise PluginActivationError(
            f"plugin activation refused; reinstall with "
            f"`birkin plugins install --upgrade`: {exc}"
        ) from exc


def entry_paths(project_root: Path, team_root: Path,
                kind: PluginKind,
                trusted_keys: Mapping[str, bytes] | None = None, *,
                allow_unsigned: bool = False) -> tuple[tuple[Path, str], ...]:
    entries: list[tuple[Path, str]] = []
    for plugin in _verified_plugins(
        project_root,
        team_root,
        trusted_keys,
        allow_unsigned=allow_unsigned,
    ):
        manifest = load_manifest(plugin.path / "birkin-plugin.json")
        for raw in manifest.entry_points.get(kind, ()):
            path = (plugin.path / raw.partition(":")[0]).resolve()
            if plugin.path.resolve() not in path.parents and path != plugin.path.resolve():
                raise PluginActivationError(f"entry point escapes bundle: {raw}")
            entries.append((path, f"plugin:{plugin.name}@{plugin.version}"))
    return tuple(entries)


def _snapshot_plugin(
    plugin: InstalledPlugin,
    trusted_keys: Mapping[str, bytes],
    allow_unsigned: bool,
) -> tuple[
    Path,
    Mapping[str, bytes],
    tempfile.TemporaryDirectory[str],
]:
    owner = tempfile.TemporaryDirectory(prefix="birkin-plugin-")
    snapshot = Path(owner.name) / "bundle"
    try:
        shutil.copytree(plugin.path, snapshot, symlinks=True)
        digest, signature = verify_bundle(
            snapshot,
            trusted_keys,
            allow_missing=allow_unsigned,
        )
    except (OSError, SignatureError) as exc:
        owner.cleanup()
        raise PluginActivationError(
            f"plugin activation snapshot verification failed: "
            f"{plugin.name}@{plugin.version}"
        ) from exc
    if digest != plugin.digest or signature != plugin.signature:
        owner.cleanup()
        raise PluginActivationError(
            "plugin activation snapshot does not match its lock record: "
            f"{plugin.name}@{plugin.version}"
        )
    try:
        captured = MappingProxyType(
            {
                path.relative_to(snapshot).as_posix(): path.read_bytes()
                for path in sorted(snapshot.rglob("*"))
                if (
                    path.is_file()
                    and path.relative_to(snapshot).as_posix() != SIGNATURE_FILE
                )
            }
        )
    except OSError as exc:
        owner.cleanup()
        raise PluginActivationError(
            f"plugin activation snapshot capture failed: "
            f"{plugin.name}@{plugin.version}"
        ) from exc
    if bundle_digest_bytes(captured) != plugin.digest:
        owner.cleanup()
        raise PluginActivationError(
            "captured plugin snapshot does not match its lock record: "
            f"{plugin.name}@{plugin.version}"
        )
    return snapshot, captured, owner


def load_agent_tools(
    project_root: Path,
    team_root: Path,
    trusted_keys: Mapping[str, bytes] | None = None,
    *,
    allow_unsigned: bool = False,
) -> list[Tool]:
    try:
        with SnapshotActivation() as activation:
            loaded: list[Tool] = []
            for plugin in _verified_plugins(
                project_root,
                team_root,
                trusted_keys,
                allow_unsigned=allow_unsigned,
            ):
                snapshot, snapshot_files, snapshot_owner = _snapshot_plugin(
                    plugin,
                    trusted_keys or {},
                    allow_unsigned,
                )
                snapshot_lifetime = activation.add_owner(snapshot_owner)
                manifest = load_manifest(
                    snapshot / "birkin-plugin.json",
                    data=snapshot_files["birkin-plugin.json"],
                )
                origin = ToolOrigin(
                    "plugin", manifest.name, manifest.version, plugin.digest)
                source = f"plugin:{plugin.name}@{plugin.version}"
                snapshot_root = snapshot.resolve()
                for raw in manifest.entry_points.get(PluginKind.AGENT, ()):
                    file_part, separator, symbol = raw.partition(":")
                    path = (snapshot / file_part).resolve()
                    if snapshot_root not in path.parents:
                        raise PluginActivationError(
                            f"entry point escapes bundle: {raw}"
                        )
                    if not separator or path.suffix != ".py":
                        raise PluginActivationError(
                            f"agent entry point must be file.py:callable: {raw}"
                        )
                    module_name = (
                        f"birkin_plugin_{plugin.digest}_{path.stem}"
                    )
                    relative = PurePosixPath(
                        path.relative_to(snapshot_root).as_posix()
                    )
                    try:
                        module = load_snapshot_module(
                            module_name,
                            snapshot_root,
                            relative,
                            snapshot_files,
                            snapshot_lifetime,
                        )
                    except SnapshotImportError as exc:
                        raise PluginActivationError(
                            f"cannot load agent entry point: {raw}"
                        ) from exc
                    factory = getattr(module, symbol, None)
                    if not callable(factory):
                        raise PluginActivationError(
                            f"agent entry point is not callable: {raw}"
                        )
                    produced = factory()
                    candidates = (
                        [produced]
                        if isinstance(produced, Tool)
                        else produced
                    )
                    if not isinstance(candidates, (list, tuple)) or not all(
                        isinstance(tool, Tool) for tool in candidates
                    ):
                        raise PluginActivationError(
                            f"{source} must return Tool or a Tool sequence"
                        )
                    loaded.extend(
                        replace(tool, origin=origin)
                        for tool in candidates
                    )
            return loaded
    except SnapshotTransactionError as exc:
        raise PluginActivationError(
            "plugin activation transaction failed"
        ) from exc.__cause__
