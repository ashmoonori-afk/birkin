from __future__ import annotations

import json
from pathlib import Path

import pytest

from birkin.sandbox import (
    NetworkPolicy,
    PolicyRequest,
    SandboxConfigError,
    SandboxPolicy,
    load_repo_sandbox,
)


def test_policy_fails_closed_for_network_and_write_scope() -> None:
    policy = SandboxPolicy(
        network=NetworkPolicy.ALLOWLIST,
        network_allowlist=("api.example.com",),
        env_allowlist=("SAFE_TOKEN",),
        write_paths=("src", "pyproject.toml"),
    )

    allowed = policy.evaluate(PolicyRequest(
        network_hosts=("api.example.com",), write_paths=("src/new.py",)
    ))
    denied = policy.evaluate(PolicyRequest(
        network_hosts=("evil.example",), write_paths=("README.md",)
    ))

    assert allowed.allowed
    assert not denied.allowed
    assert denied.reasons == (
        "network destination is not allowlisted: evil.example",
        "write is outside the allowed scope: README.md",
    )


def test_environment_contains_only_explicitly_allowlisted_names() -> None:
    policy = SandboxPolicy(env_allowlist=("SAFE_TOKEN",))

    assert policy.environment({
        "SAFE_TOKEN": "kept", "HOME": "/secret", "AWS_SECRET_ACCESS_KEY": "nope"
    }) == {"SAFE_TOKEN": "kept"}


@pytest.mark.parametrize("path", ["../escape", "/absolute", "C:/escape"])
def test_invalid_write_scope_is_rejected(path: str) -> None:
    with pytest.raises(SandboxConfigError, match="relative repo path"):
        SandboxPolicy(write_paths=(path,))


def test_repo_config_is_reproducible_and_validated(tmp_path: Path) -> None:
    config_dir = tmp_path / ".birkin"
    config_dir.mkdir()
    (config_dir / "sandbox.json").write_text(json.dumps({
        "backend": "docker",
        "image": "python:3.12.4-slim@sha256:" + "a" * 64,
        "setup": ["python -m pip install -e ."],
        "env_allowlist": ["PIP_INDEX_URL"],
        "network": "allowlist",
        "network_allowlist": ["pypi.org"],
        "write_paths": ["src", "tests"],
    }), encoding="utf-8")

    spec = load_repo_sandbox(tmp_path)

    assert spec.backend == "docker"
    assert spec.setup == ("python -m pip install -e .",)
    assert spec.policy.network is NetworkPolicy.ALLOWLIST
    assert spec.policy.write_paths == ("src", "tests")

    (config_dir / "sandbox.json").write_text('{"backend":"vm"}', encoding="utf-8")
    with pytest.raises(SandboxConfigError, match="backend"):
        load_repo_sandbox(tmp_path)
