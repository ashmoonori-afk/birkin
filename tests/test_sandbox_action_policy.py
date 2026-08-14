from birkin.github_action import sandbox_policy_decision
from birkin.sandbox import (
    NetworkPolicy,
    PolicyRequest,
    SandboxPolicy,
    local_policy_decision,
)


def test_local_and_action_workers_use_identical_policy_decision() -> None:
    policy = SandboxPolicy(
        network=NetworkPolicy.ALLOWLIST,
        network_allowlist=("github.com",), write_paths=("birkin", "tests")
    )
    request = PolicyRequest(
        network_hosts=("example.com",), write_paths=("README.md",)
    )

    local = local_policy_decision(policy, request)
    remote = sandbox_policy_decision(policy, request)

    assert remote is local
    assert not remote.allowed
