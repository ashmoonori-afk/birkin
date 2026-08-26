from __future__ import annotations

import json
from pathlib import Path

import pytest

from birkin import plugin_install
from birkin.plugin_install import (
    InstallConfirmationRequired,
    PluginInstallError,
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
    assert lock["bundles"]["acme-review"]["signature"] == "verified:test"


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


def test_bundle_manifest_cannot_authorize_its_own_unsigned_install(tmp_path: Path):
    with pytest.raises(SignatureError, match="missing"):
        _installer(tmp_path).inspect(_bundle(tmp_path / "bundle", unsigned=True))


def test_operator_may_explicitly_allow_unsigned_bundle(tmp_path: Path):
    installer = PluginInstaller(
        tmp_path / "project",
        tmp_path / "team",
        {"test": KEY},
        allow_unsigned=True,
    )
    record = installer.inspect(_bundle(tmp_path / "bundle", unsigned=True))
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
    installer = PluginInstaller(
        tmp_path / "project",
        tmp_path / "team",
        {"test": KEY},
        allow_unsigned=True,
    )
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


@pytest.mark.parametrize("stored_path", ["/tmp/external", "../external"])
def test_upgrade_refuses_uncontained_lock_record_path(
    tmp_path: Path,
    stored_path: str,
):
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "sentinel.txt"
    sentinel.write_text("unchanged", encoding="utf-8")
    root = tmp_path / "project"
    root.mkdir()
    if stored_path.startswith("/"):
        stored_path = str(external)
    (root / "registry.lock").write_text(
        json.dumps(
            {
                "lock_version": 1,
                "scope": "project",
                "bundles": {
                    "acme-review": {
                        "version": "0.9.0",
                        "digest": "old",
                        "path": stored_path,
                        "kinds": ["skill"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    bundle = _bundle(tmp_path / "bundle", "1.0.0")
    sign_bundle(bundle, "test", KEY)

    with pytest.raises(PluginInstallError, match="path"):
        _installer(tmp_path).install(
            bundle,
            Scope.PROJECT,
            "1.0.0",
            confirmed=True,
            upgrade=True,
        )

    assert sentinel.read_text(encoding="utf-8") == "unchanged"


def test_upgrade_refuses_symlinked_installed_bundle_path(tmp_path: Path):
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "sentinel.txt"
    sentinel.write_text("unchanged", encoding="utf-8")
    root = tmp_path / "project"
    old = root / "bundles" / "acme-review" / "0.9.0"
    old.parent.mkdir(parents=True)
    old.symlink_to(external, target_is_directory=True)
    (root / "registry.lock").write_text(
        json.dumps(
            {
                "lock_version": 1,
                "scope": "project",
                "bundles": {
                    "acme-review": {
                        "version": "0.9.0",
                        "digest": "old",
                        "path": "bundles/acme-review/0.9.0",
                        "kinds": ["skill"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    bundle = _bundle(tmp_path / "bundle", "1.0.0")
    sign_bundle(bundle, "test", KEY)

    with pytest.raises(PluginInstallError, match="symbolic link"):
        _installer(tmp_path).install(
            bundle,
            Scope.PROJECT,
            "1.0.0",
            confirmed=True,
            upgrade=True,
        )

    assert sentinel.read_text(encoding="utf-8") == "unchanged"


def test_install_verifies_staging_copy_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    bundle = _bundle(tmp_path / "bundle")
    sign_bundle(bundle, "test", KEY)
    original_verify_bundle = plugin_install.verify_bundle
    verification_count = 0

    def tampering_verify_bundle(
        root: Path,
        trusted_keys: dict[str, bytes],
        *,
        allow_missing: bool,
    ) -> tuple[str, str]:
        nonlocal verification_count
        verification_count += 1
        if verification_count == 2:
            (root / "skills" / "review" / "SKILL.md").write_text(
                "replacement",
                encoding="utf-8",
            )
        return original_verify_bundle(
            root,
            trusted_keys,
            allow_missing=allow_missing,
        )

    monkeypatch.setattr(plugin_install, "verify_bundle", tampering_verify_bundle)

    with pytest.raises(SignatureError, match="mismatch"):
        _installer(tmp_path).install(
            bundle,
            Scope.PROJECT,
            "1.0.0",
            confirmed=True,
        )

    assert not (tmp_path / "project" / "registry.lock").exists()
