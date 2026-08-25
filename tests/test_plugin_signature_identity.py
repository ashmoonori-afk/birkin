from __future__ import annotations

import json
import sys
import threading
from collections.abc import Mapping
from pathlib import Path
from pathlib import PurePosixPath
from types import ModuleType

import pytest

from birkin import plugin_runtime
from birkin.plugin_install import PluginInstaller, Scope
from birkin.plugin_runtime import PluginActivationError
from birkin.plugin_signature import (
    bundle_digest,
    bundle_digest_bytes,
    sign_bundle,
)
from birkin.plugin_snapshot import SnapshotLifetime


KEY = b"signature-identity-test-key"


def _resource_bundle(root: Path) -> Path:
    package = root / "plugin_package"
    package.mkdir(parents=True)
    (package / "bundle.sig").write_text(
        "captured-resource",
        encoding="utf-8",
    )
    (package / "__init__.py").write_text(
        "from importlib.resources import files\n"
        "from birkin.tools import Tool, ToolResult\n"
        "RESOURCE = files(__package__).joinpath("
        "'bundle.sig').read_text(encoding='utf-8')\n"
        "def tools():\n"
        " return [Tool('signature_resource', RESOURCE, {'type':'object'}, "
        "lambda inp, ctx: ToolResult('ok'))]\n",
        encoding="utf-8",
    )
    (root / "birkin-plugin.json").write_text(
        json.dumps(
            {
                "name": "signature-resource-agent",
                "version": "1.0.0",
                "kinds": ["agent"],
                "entry_points": {
                    "agent": ["plugin_package/__init__.py:tools"],
                },
                "required_permissions": {
                    "network": "off",
                    "network_allowlist": [],
                    "env_allowlist": [],
                    "write_paths": [],
                },
            }
        ),
        encoding="utf-8",
    )
    sign_bundle(root, "signature-test", KEY)
    return root


def test_bundle_digest_excludes_only_root_detached_signature(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    nested = root / "plugin_package"
    nested.mkdir(parents=True)
    (root / "bundle.sig").write_bytes(b"root-one")
    (nested / "bundle.sig").write_bytes(b"nested-one")
    (root / "ordinary.txt").write_bytes(b"ordinary")
    original_path_digest = bundle_digest(root)
    original_bytes_digest = bundle_digest_bytes(
        {
            "bundle.sig": b"root-one",
            "plugin_package/bundle.sig": b"nested-one",
            "ordinary.txt": b"ordinary",
        }
    )

    (root / "bundle.sig").write_bytes(b"root-two")
    assert bundle_digest(root) == original_path_digest
    assert bundle_digest_bytes(
        {
            "bundle.sig": b"root-two",
            "plugin_package/bundle.sig": b"nested-one",
            "ordinary.txt": b"ordinary",
        }
    ) == original_bytes_digest

    (nested / "bundle.sig").write_bytes(b"nested-two")
    assert bundle_digest(root) != original_path_digest
    assert bundle_digest_bytes(
        {
            "bundle.sig": b"root-two",
            "plugin_package/bundle.sig": b"nested-two",
            "ordinary.txt": b"ordinary",
        }
    ) != original_bytes_digest


def test_plugin_rejects_mutated_nested_signature_named_resource(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project-registry"
    team = tmp_path / "team-registry"
    installed = PluginInstaller(
        project,
        team,
        {"signature-test": KEY},
    ).install(
        _resource_bundle(tmp_path / "bundle"),
        Scope.PROJECT,
        "1.0.0",
        confirmed=True,
    )
    original_verify = plugin_runtime.verify_bundle
    snapshot_verified = threading.Event()
    release = threading.Event()
    snapshot: Path | None = None

    def verify_then_wait(
        root: Path,
        trusted_keys: dict[str, bytes],
        *,
        allow_missing: bool,
    ) -> tuple[str, str]:
        nonlocal snapshot
        result = original_verify(
            root,
            trusted_keys,
            allow_missing=allow_missing,
        )
        if root != installed.path and root.name == "bundle":
            snapshot = root
            snapshot_verified.set()
            assert release.wait(timeout=5)
        return result

    monkeypatch.setattr(plugin_runtime, "verify_bundle", verify_then_wait)
    errors: list[PluginActivationError] = []
    descriptions: list[str] = []

    def activate() -> None:
        try:
            tools = plugin_runtime.load_agent_tools(
                project,
                team,
                {"signature-test": KEY},
            )
            descriptions.extend(tool.description for tool in tools)
        except PluginActivationError as exc:
            errors.append(exc)

    thread = threading.Thread(target=activate)
    thread.start()
    assert snapshot_verified.wait(timeout=5)
    assert snapshot is not None
    try:
        (snapshot / "plugin_package" / "bundle.sig").write_text(
            "mutated-resource",
            encoding="utf-8",
        )
    finally:
        release.set()
        thread.join(timeout=5)
        sys.modules.pop(
            f"birkin_plugin_{installed.digest}___init__",
            None,
        )

    assert not thread.is_alive()
    assert len(errors) == 1
    assert "mutated-resource" not in descriptions


def test_root_detached_signature_is_not_in_loader_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project-registry"
    team = tmp_path / "team-registry"
    installed = PluginInstaller(
        project,
        team,
        {"signature-test": KEY},
    ).install(
        _resource_bundle(tmp_path / "bundle"),
        Scope.PROJECT,
        "1.0.0",
        confirmed=True,
    )
    original_load = plugin_runtime.load_snapshot_module
    captured_names: list[set[str]] = []

    def record_mapping(
        module_name: str,
        root: Path,
        entry: PurePosixPath,
        files: Mapping[str, bytes],
        lifetime: SnapshotLifetime,
    ) -> ModuleType:
        captured_names.append(set(files))
        return original_load(
            module_name,
            root,
            entry,
            files,
            lifetime,
        )

    monkeypatch.setattr(plugin_runtime, "load_snapshot_module", record_mapping)
    try:
        plugin_runtime.load_agent_tools(
            project,
            team,
            {"signature-test": KEY},
        )
    finally:
        sys.modules.pop(
            f"birkin_plugin_{installed.digest}___init__",
            None,
        )

    assert captured_names
    assert "bundle.sig" not in captured_names[0]
