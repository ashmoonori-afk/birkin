"""Activation adapters from installed bundles into Birkin's existing registries."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from .plugin_install import InstalledPlugin, PluginInstallError, PluginInstaller
from .plugin_manifest import PluginKind, load_manifest
from .plugin_signature import SignatureError, verify_bundle
from .tool_effects import ToolOrigin
from .tools._types import Tool


class PluginActivationError(RuntimeError):
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


def load_agent_tools(
    project_root: Path,
    team_root: Path,
    trusted_keys: Mapping[str, bytes] | None = None,
    *,
    allow_unsigned: bool = False,
) -> list[Tool]:
    loaded: list[Tool] = []
    for plugin in _verified_plugins(
        project_root,
        team_root,
        trusted_keys,
        allow_unsigned=allow_unsigned,
    ):
        manifest = load_manifest(plugin.path / "birkin-plugin.json")
        origin = ToolOrigin(
            "plugin", manifest.name, manifest.version, plugin.digest)
        source = f"plugin:{plugin.name}@{plugin.version}"
        for raw in manifest.entry_points.get(PluginKind.AGENT, ()):
            file_part, separator, symbol = raw.partition(":")
            path = (plugin.path / file_part).resolve()
            if plugin.path.resolve() not in path.parents:
                raise PluginActivationError(f"entry point escapes bundle: {raw}")
            if not separator or path.suffix != ".py":
                raise PluginActivationError(f"agent entry point must be file.py:callable: {raw}")
            module_name = f"birkin_plugin_{plugin.digest}_{path.stem}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise PluginActivationError(f"cannot load agent entry point: {raw}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            factory = getattr(module, symbol, None)
            if not callable(factory):
                raise PluginActivationError(f"agent entry point is not callable: {raw}")
            produced = factory()
            candidates = [produced] if isinstance(produced, Tool) else produced
            if not isinstance(candidates, (list, tuple)) or not all(
                isinstance(tool, Tool) for tool in candidates
            ):
                raise PluginActivationError(f"{source} must return Tool or a Tool sequence")
            loaded.extend(
                replace(tool, origin=origin) for tool in candidates)
    return loaded
