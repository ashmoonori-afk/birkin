"""Shared, fail-closed execution policy and per-repository sandbox config."""

from __future__ import annotations

import json
import ntpath
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Mapping


class SandboxError(RuntimeError):
    """Base class for sandbox failures."""


class SandboxConfigError(SandboxError, ValueError):
    """A repository sandbox declaration is invalid."""


class SandboxViolation(SandboxError, PermissionError):
    """A requested or observed operation violates sandbox policy."""


class NetworkPolicy(str, Enum):
    OFF = "off"
    ALLOWLIST = "allowlist"


@dataclass(frozen=True)
class PolicyRequest:
    network_hosts: tuple[str, ...] = ()
    write_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reasons: tuple[str, ...] = ()


def _repo_path(raw: str) -> PurePosixPath:
    normalized = raw.replace("\\", "/")
    path = PurePosixPath(normalized)
    drive, _ = ntpath.splitdrive(raw)
    if not raw or drive or path.is_absolute() or ".." in path.parts:
        raise SandboxConfigError(f"write scope must be a relative repo path: {raw!r}")
    return path


def _contains(scope: PurePosixPath, candidate: PurePosixPath) -> bool:
    return scope == PurePosixPath(".") or candidate == scope or scope in candidate.parents


@dataclass(frozen=True)
class SandboxPolicy:
    network: NetworkPolicy = NetworkPolicy.OFF
    network_allowlist: tuple[str, ...] = ()
    env_allowlist: tuple[str, ...] = ()
    write_paths: tuple[str, ...] = (".",)
    _scopes: tuple[PurePosixPath, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        try:
            network = NetworkPolicy(self.network)
        except ValueError as exc:
            raise SandboxConfigError(f"invalid network policy: {self.network!r}") from exc
        object.__setattr__(self, "network", network)
        object.__setattr__(self, "_scopes", tuple(_repo_path(p) for p in self.write_paths))
        if not self.write_paths:
            object.__setattr__(self, "_scopes", ())
        for name in self.env_allowlist:
            if not name or not name.replace("_", "A").isalnum():
                raise SandboxConfigError(f"invalid environment name: {name!r}")
        if network is NetworkPolicy.OFF and self.network_allowlist:
            raise SandboxConfigError("network_allowlist requires network='allowlist'")

    @lru_cache(maxsize=256)
    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        reasons: list[str] = []
        hosts = {host.lower().rstrip(".") for host in self.network_allowlist}
        for host in request.network_hosts:
            normalized = host.lower().rstrip(".")
            if self.network is NetworkPolicy.OFF:
                reasons.append(f"network is disabled: {host}")
            elif normalized not in hosts:
                reasons.append(f"network destination is not allowlisted: {host}")
        for raw in request.write_paths:
            try:
                path = _repo_path(raw)
            except SandboxConfigError:
                reasons.append(f"write is outside the allowed scope: {raw}")
                continue
            if not any(_contains(scope, path) for scope in self._scopes):
                reasons.append(f"write is outside the allowed scope: {raw}")
        return PolicyDecision(not reasons, tuple(reasons))

    def environment(self, source: Mapping[str, str]) -> dict[str, str]:
        return {name: source[name] for name in self.env_allowlist if name in source}

    def require(self, request: PolicyRequest) -> PolicyDecision:
        decision = self.evaluate(request)
        if not decision.allowed:
            raise SandboxViolation("; ".join(decision.reasons))
        return decision


@dataclass(frozen=True)
class SandboxSpec:
    backend: str = "worktree"
    image: str = ""
    setup: tuple[str, ...] = ()
    policy: SandboxPolicy = field(default_factory=SandboxPolicy)


@dataclass(frozen=True)
class SandboxJob:
    command: tuple[str, ...]
    setup: tuple[str, ...] = ()
    image: str = ""
    request: PolicyRequest = field(default_factory=PolicyRequest)


@dataclass(frozen=True)
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str = ""


def local_policy_decision(policy: SandboxPolicy, request: PolicyRequest) -> PolicyDecision:
    return policy.evaluate(request)


def run_repo_job(
    repo: Path,
    command: tuple[str, ...],
    *,
    request: PolicyRequest = PolicyRequest(),
    defaults: Mapping[str, object] | None = None,
    source_env: Mapping[str, str] | None = None,
) -> SandboxResult:
    """Load the repository declaration and execute through its selected backend."""
    spec = load_repo_sandbox(repo, defaults)
    job = SandboxJob(command, spec.setup, spec.image, request)
    if spec.backend == "worktree":
        from .sandbox_worktree import WorktreeRunner
        return WorktreeRunner(repo).run(job, spec.policy, source_env=source_env)
    if spec.backend == "docker":
        from .sandbox_docker import DockerRunner
        return DockerRunner(repo).run(job, spec.policy, source_env=source_env)
    raise AssertionError(f"unhandled sandbox backend: {spec.backend}")


def load_repo_sandbox(repo: Path, defaults: Mapping[str, object] | None = None) -> SandboxSpec:
    raw: object = dict(defaults or {})
    path = repo / ".birkin" / "sandbox.json"
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SandboxConfigError(f"invalid {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SandboxConfigError("sandbox config must be an object")
    backend = raw.get("backend", "worktree")
    if backend not in ("worktree", "docker"):
        raise SandboxConfigError("backend must be 'worktree' or 'docker'")
    image = raw.get("image", "")
    setup = raw.get("setup", [])
    if not isinstance(image, str) or not isinstance(setup, list) or not all(isinstance(x, str) for x in setup):
        raise SandboxConfigError("image must be a string and setup must be a string array")
    if backend == "docker" and not image:
        raise SandboxConfigError("docker backend requires a pinned image")
    def strings(name: str, default: list[str]) -> tuple[str, ...]:
        value = raw.get(name, default)
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise SandboxConfigError(f"{name} must be a string array")
        return tuple(value)
    policy = SandboxPolicy(
        network=NetworkPolicy(str(raw.get("network", "off"))),
        network_allowlist=strings("network_allowlist", []),
        env_allowlist=strings("env_allowlist", []),
        write_paths=strings("write_paths", ["."]),
    )
    return SandboxSpec(str(backend), image, tuple(setup), policy)
