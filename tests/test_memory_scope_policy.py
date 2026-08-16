from pathlib import Path

import pytest

from birkin.memory_scopes import (
    MemoryAccessPolicy,
    MemoryOperation,
    MemoryScope,
    PolicyRequest,
    SCOPE_PRECEDENCE,
    SharedBlockWriteError,
    TrustLevel,
    VisibilityDeniedError,
    scope_root,
)


def test_scope_precedence_is_most_specific_first():
    assert SCOPE_PRECEDENCE == (
        MemoryScope.WORKFLOW,
        MemoryScope.AGENT,
        MemoryScope.PROJECT,
        MemoryScope.ORGANIZATION,
        MemoryScope.USER,
    )


def test_each_scope_has_a_stable_vault_location():
    vault = Path("vault")
    assert scope_root(vault, MemoryScope.USER) == vault
    for scope in SCOPE_PRECEDENCE[:-1]:
        assert scope_root(vault, scope) == vault / ".birkin-scopes" / scope.value


def test_shared_read_only_block_refuses_non_owner_write_with_typed_error():
    policy = MemoryAccessPolicy(
        actor_scope=MemoryScope.AGENT,
        read_scopes=frozenset(SCOPE_PRECEDENCE),
    )

    assert policy.require(PolicyRequest(MemoryOperation.READ, MemoryScope.PROJECT)).allowed
    with pytest.raises(SharedBlockWriteError):
        policy.require(PolicyRequest(
            MemoryOperation.WRITE,
            MemoryScope.PROJECT,
            shared_read_only=True,
        ))


def test_visibility_denial_is_typed_and_fail_closed():
    policy = MemoryAccessPolicy(
        actor_scope=MemoryScope.AGENT,
        read_scopes=frozenset({MemoryScope.USER, MemoryScope.AGENT}),
    )

    decision = policy.evaluate(PolicyRequest(MemoryOperation.READ, MemoryScope.ORGANIZATION))
    assert decision.allowed is False
    with pytest.raises(VisibilityDeniedError):
        policy.require(PolicyRequest(MemoryOperation.READ, MemoryScope.ORGANIZATION))


def test_per_source_trust_uses_ordered_thresholds():
    policy = MemoryAccessPolicy(
        source_trust=(("signed-import", TrustLevel.HIGH), ("chat", TrustLevel.LOW)),
        default_trust=TrustLevel.MEDIUM,
    )

    assert policy.trust_for("signed-import") is TrustLevel.HIGH
    assert policy.trust_for("unknown") is TrustLevel.MEDIUM
    assert policy.meets_trust("chat", TrustLevel.MEDIUM) is False
    assert policy.meets_trust("chat", TrustLevel.LOW) is True
