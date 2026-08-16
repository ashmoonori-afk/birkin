from __future__ import annotations

import json
from pathlib import Path

import pytest

from birkin.plugin_manifest import ManifestError, PluginKind, load_manifest
from birkin.sandbox import NetworkPolicy, SandboxPolicy


def _write(path: Path, **overrides: object) -> Path:
    data: dict[str, object] = {
        "name": "acme-tools",
        "version": "1.2.3",
        "kinds": ["skill", "agent"],
        "entry_points": {
            "skill": ["skills/review"],
            "agent": ["agent.py:tools"],
        },
        "required_permissions": {
            "network": "allowlist",
            "network_allowlist": ["api.example.com"],
            "env_allowlist": ["ACME_TOKEN"],
            "write_paths": ["reports"],
        },
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_manifest_parses_kinds_entry_points_and_existing_policy(tmp_path: Path):
    manifest = load_manifest(_write(tmp_path / "birkin-plugin.json"))

    assert manifest.name == "acme-tools"
    assert manifest.version == "1.2.3"
    assert manifest.kinds == (PluginKind.SKILL, PluginKind.AGENT)
    assert manifest.entry_points[PluginKind.SKILL] == ("skills/review",)
    assert manifest.permissions == SandboxPolicy(
        network=NetworkPolicy.ALLOWLIST,
        network_allowlist=("api.example.com",),
        env_allowlist=("ACME_TOKEN",),
        write_paths=("reports",),
    )
    assert manifest.requires_confirmation is True


def test_read_only_manifest_needs_no_confirmation(tmp_path: Path):
    path = _write(
        tmp_path / "birkin-plugin.json",
        kinds=["skill"],
        entry_points={"skill": ["skills/review"]},
        required_permissions={
            "network": "off",
            "network_allowlist": [],
            "env_allowlist": [],
            "write_paths": [],
        },
    )
    assert load_manifest(path).requires_confirmation is False


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"version": "latest"}, "exact semantic version"),
        ({"kinds": ["tool"]}, "invalid kind"),
        ({"entry_points": {"skill": ["../escape"]}}, "entry point"),
        ({"required_permissions": {"network": "off"}}, "must contain exactly"),
        ({"unsigned_allowed": "yes"}, "unsigned_allowed"),
    ],
)
def test_manifest_rejects_invalid_or_ambiguous_input(
    tmp_path: Path, override: dict[str, object], message: str
):
    with pytest.raises(ManifestError, match=message):
        load_manifest(_write(tmp_path / "birkin-plugin.json", **override))
