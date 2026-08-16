from __future__ import annotations

import json
from pathlib import Path

import pytest

from birkin.plugin_install import (
    InstallConfirmationRequired,
    PluginInstaller,
    Scope,
    VersionConflict,
)
from birkin.plugin_signature import SignatureError, sign_bundle

KEY = b"fixture-secret-key"


def _bundle(root: Path, version: str = "1.0.0", *, unsigned: bool = False,
            writable: bool = True) -> Path:
    root.mkdir(parents=True)
    (root / "skills" / "review").mkdir(parents=True)
    (root / "skills" / "review" / "SKILL.md").write_text("# Review\n", encoding="utf-8")
    manifest = {
        "name": "acme-review",
        "version": version,
        "kinds": ["skill"],
        "entry_points": {"skill": ["skills/review"]},
        "required_permissions": {
            "network": "off",
            "network_allowlist": [],
            "env_allowlist": [],
            "write_paths": ["reports"] if writable else [],
        },
        "unsigned_allowed": unsigned,
    }
    (root / "birkin-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def _installer(tmp_path: Path) -> PluginInstaller:
    return PluginInstaller(tmp_path / "project", tmp_path / "team", {"test": KEY})


def test_signed_install_is_pinned_and_recorded_in_lockfile(tmp_path: Path):
    bundle = _bundle(tmp_path / "bundle")
    sign_bundle(bundle, "test", KEY)
    installer = _installer(tmp_path)

    installed = installer.install(bundle, Scope.PROJECT, "1.0.0", confirmed=True)

    assert installed.version == "1.0.0"
    assert (installed.path / "skills" / "review" / "SKILL.md").is_file()
    lock = json.loads((tmp_path / "project" / "registry.lock").read_text(encoding="utf-8"))
    assert lock["bundles"]["acme-review"]["version"] == "1.0.0"
    assert lock["bundles"]["acme-review"]["digest"]


def test_signature_fails_closed_for_missing_tampered_and_unknown_key(tmp_path: Path):
    installer = _installer(tmp_path)
    unsigned = _bundle(tmp_path / "unsigned")
    with pytest.raises(SignatureError, match="missing"):
        installer.inspect(unsigned)

    signed = _bundle(tmp_path / "signed")
    sign_bundle(signed, "test", KEY)
    (signed / "skills" / "review" / "SKILL.md").write_text("tampered", encoding="utf-8")
    with pytest.raises(SignatureError, match="mismatch"):
        installer.inspect(signed)

    unknown = _bundle(tmp_path / "unknown")
    sign_bundle(unknown, "other", KEY)
    with pytest.raises(SignatureError, match="untrusted key"):
        installer.inspect(unknown)


def test_manifest_may_explicitly_allow_unsigned_bundle(tmp_path: Path):
    record = _installer(tmp_path).inspect(_bundle(tmp_path / "bundle", unsigned=True))
    assert record.signature == "unsigned-allowed"


def test_permissions_are_disclosed_before_confirmation_and_refusal_writes_nothing(
    tmp_path: Path,
):
    bundle = _bundle(tmp_path / "bundle")
    sign_bundle(bundle, "test", KEY)
    installer = _installer(tmp_path)
    seen: list[dict[str, object]] = []

    with pytest.raises(InstallConfirmationRequired):
        installer.install(
            bundle, Scope.PROJECT, "1.0.0", confirmed=False,
            disclose=lambda record: seen.append(record.machine_record()),
        )

    assert seen[0]["permissions"] == {
        "network": "off", "network_allowlist": [],
        "env_allowlist": [], "write_paths": ["reports"],
    }
    assert not (tmp_path / "project" / "registry.lock").exists()


def test_read_only_bundle_installs_without_confirmation(tmp_path: Path):
    bundle = _bundle(tmp_path / "bundle", writable=False)
    sign_bundle(bundle, "test", KEY)
    assert _installer(tmp_path).install(bundle, Scope.PROJECT, "1.0.0").version == "1.0.0"


def test_upgrade_is_explicit_and_resolution_prefers_project_scope(tmp_path: Path):
    installer = _installer(tmp_path)
    team = _bundle(tmp_path / "team-bundle", "1.0.0", unsigned=True, writable=False)
    project = _bundle(tmp_path / "project-bundle", "2.0.0", unsigned=True, writable=False)
    installer.install(team, Scope.TEAM, "1.0.0")
    installer.install(project, Scope.PROJECT, "2.0.0")

    assert installer.resolve("acme-review").scope is Scope.PROJECT
    assert installer.resolve("acme-review").version == "2.0.0"
    with pytest.raises(VersionConflict, match="project scope pins 2.0.0"):
        installer.resolve("acme-review", "1.0.0")

    newer = _bundle(tmp_path / "newer", "3.0.0", unsigned=True, writable=False)
    with pytest.raises(VersionConflict, match="--upgrade"):
        installer.install(newer, Scope.PROJECT, "3.0.0")
    assert installer.install(newer, Scope.PROJECT, "3.0.0", upgrade=True).version == "3.0.0"
