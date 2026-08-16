"""Typed scope, trust, and visibility policy for vault memory."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class MemoryPolicyError(RuntimeError):
    """Base class for memory policy failures."""


class MemoryPolicyConfigError(MemoryPolicyError, ValueError):
    """A scope or trust policy declaration is invalid."""


class VisibilityDeniedError(MemoryPolicyError, PermissionError):
    """The actor cannot read the owning scope."""


class ScopeWriteDeniedError(MemoryPolicyError, PermissionError):
    """The actor does not own the target scope."""


class SharedBlockWriteError(ScopeWriteDeniedError):
    """A non-owner tried to modify a shared read-only block."""


class MemoryScope(str, Enum):
    USER = "user"
    PROJECT = "project"
    ORGANIZATION = "organization"
    AGENT = "agent"
    WORKFLOW = "workflow"


# Most execution-specific value wins when the same slug exists in many scopes.
SCOPE_PRECEDENCE = (
    MemoryScope.WORKFLOW,
    MemoryScope.AGENT,
    MemoryScope.PROJECT,
    MemoryScope.ORGANIZATION,
    MemoryScope.USER,
)


class TrustLevel(str, Enum):
    UNTRUSTED = "untrusted"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MemoryOperation(str, Enum):
    READ = "read"
    WRITE = "write"


def parse_scope(raw: object) -> MemoryScope:
    try:
        return raw if isinstance(raw, MemoryScope) else MemoryScope(str(raw))
    except ValueError as exc:
        raise MemoryPolicyConfigError(f"invalid memory scope: {raw!r}") from exc


def parse_trust(raw: object) -> TrustLevel:
    try:
        return raw if isinstance(raw, TrustLevel) else TrustLevel(str(raw))
    except ValueError as exc:
        raise MemoryPolicyConfigError(f"invalid memory trust level: {raw!r}") from exc


def _trust_rank(level: TrustLevel) -> int:
    match level:
        case TrustLevel.UNTRUSTED:
            return 0
        case TrustLevel.LOW:
            return 1
        case TrustLevel.MEDIUM:
            return 2
        case TrustLevel.HIGH:
            return 3
    raise AssertionError(f"unhandled trust level: {level!r}")


def scope_root(vault: Path, scope: MemoryScope) -> Path:
    """Return the stable storage root; user deliberately keeps legacy layout."""
    match scope:
        case MemoryScope.USER:
            return vault
        case (MemoryScope.PROJECT | MemoryScope.ORGANIZATION
              | MemoryScope.AGENT | MemoryScope.WORKFLOW):
            return vault / ".birkin-scopes" / scope.value
    raise AssertionError(f"unhandled memory scope: {scope!r}")


@dataclass(frozen=True)
class PolicyRequest:
    operation: MemoryOperation
    owner_scope: MemoryScope
    shared_read_only: bool = False


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryAccessPolicy:
    """Fail-closed policy using the same evaluate/require shape as sandbox."""

    actor_scope: MemoryScope = MemoryScope.USER
    read_scopes: frozenset[MemoryScope] = frozenset(SCOPE_PRECEDENCE)
    source_trust: tuple[tuple[str, TrustLevel], ...] = ()
    default_trust: TrustLevel = TrustLevel.MEDIUM

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any]) -> "MemoryAccessPolicy":
        actor = parse_scope(cfg.get("memory_scope", MemoryScope.USER.value))
        raw_visible = cfg.get("memory_visible_scopes", [s.value for s in SCOPE_PRECEDENCE])
        if not isinstance(raw_visible, list):
            raise MemoryPolicyConfigError("memory_visible_scopes must be an array")
        visible = frozenset(parse_scope(item) for item in raw_visible)
        raw_trust = cfg.get("memory_source_trust", {})
        if not isinstance(raw_trust, Mapping):
            raise MemoryPolicyConfigError("memory_source_trust must be an object")
        source_trust = tuple(
            (str(source), parse_trust(level)) for source, level in raw_trust.items()
        )
        return cls(actor, visible, source_trust,
                   parse_trust(cfg.get("memory_default_trust", "medium")))

    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        match request.operation:
            case MemoryOperation.READ:
                if request.owner_scope not in self.read_scopes:
                    return PolicyDecision(False, (
                        f"memory scope is not visible: {request.owner_scope.value}",
                    ))
                return PolicyDecision(True)
            case MemoryOperation.WRITE:
                if request.owner_scope is not self.actor_scope:
                    label = "shared read-only block" if request.shared_read_only else "scope"
                    return PolicyDecision(False, (
                        f"{label} is owned by {request.owner_scope.value}",
                    ))
                return PolicyDecision(True)
        raise AssertionError(f"unhandled memory operation: {request.operation!r}")

    def require(self, request: PolicyRequest) -> PolicyDecision:
        decision = self.evaluate(request)
        if decision.allowed:
            return decision
        message = "; ".join(decision.reasons)
        match request.operation:
            case MemoryOperation.READ:
                raise VisibilityDeniedError(message)
            case MemoryOperation.WRITE:
                if request.shared_read_only:
                    raise SharedBlockWriteError(message)
                raise ScopeWriteDeniedError(message)
        raise AssertionError(f"unhandled memory operation: {request.operation!r}")

    def trust_for(self, source: str) -> TrustLevel:
        for configured_source, level in self.source_trust:
            if configured_source == source:
                return level
        return self.default_trust

    def meets_trust(self, source: str, minimum: TrustLevel) -> bool:
        return _trust_rank(self.trust_for(source)) >= _trust_rank(minimum)

    def readable_scopes(self) -> tuple[MemoryScope, ...]:
        return tuple(scope for scope in SCOPE_PRECEDENCE if scope in self.read_scopes)
