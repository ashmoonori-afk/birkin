"""Parse Action YAML and pin the least-privilege/fork-safety contract."""

from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_action_declares_only_documented_secret_inputs() -> None:
    action = _yaml(ROOT / "action.yml")
    assert action["runs"]["using"] == "composite"
    assert set(action["inputs"]) == {
        "github-token", "anthropic-api-key", "openai-api-key", "provider",
        "model", "test-command", "max-retries",
    }
    assert action["inputs"]["github-token"]["required"] is True
    steps = action["runs"]["steps"]
    execute = next(step for step in steps if step.get("id") == "execute")
    assert execute["env"]["GH_TOKEN"] == "${{ inputs.github-token }}"
    assert execute["env"]["ANTHROPIC_API_KEY"] == "${{ inputs.anthropic-api-key }}"
    assert execute["env"]["OPENAI_API_KEY"] == "${{ inputs.openai-api-key }}"


def test_action_passes_untrusted_inputs_only_through_environment() -> None:
    action = _yaml(ROOT / "action.yml")
    execute = next(
        step
        for step in action["runs"]["steps"]
        if step.get("id") == "execute"
    )

    assert "${{ inputs." not in execute["run"]
    assert execute["env"]["BIRKIN_PROVIDER"] == "${{ inputs.provider }}"
    assert execute["env"]["BIRKIN_MODEL"] == "${{ inputs.model }}"
    assert execute["env"]["BIRKIN_TEST_COMMAND"] == (
        "${{ inputs.test-command }}"
    )
    assert execute["env"]["BIRKIN_MAX_RETRIES"] == (
        "${{ inputs.max-retries }}"
    )
    assert '"$BIRKIN_TEST_COMMAND"' in execute["run"]


def test_mention_workflow_is_trusted_issue_comment_only() -> None:
    workflow = _yaml(ROOT / ".github" / "workflows" / "birkin.yml")
    # PyYAML implements YAML 1.1 and reads GitHub's YAML 1.2 ``on`` as True.
    triggers = workflow.get("on", workflow.get(True))
    assert triggers == {"issue_comment": {"types": ["created"]}}
    assert workflow["permissions"] == {"contents": "read"}

    job = workflow["jobs"]["birkin"]
    assert job["permissions"] == {
        "contents": "write", "issues": "write", "pull-requests": "write",
    }
    condition = job["if"]
    assert "author_association" in condition
    assert all(role in condition for role in ("OWNER", "MEMBER", "COLLABORATOR"))
    assert "startsWith" in condition and "'/birkin'" in condition
    assert "pull_request_target" not in (ROOT / ".github" / "workflows" / "birkin.yml").read_text()

    checkout = next(
        step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["with"]["ref"] == "${{ github.event.repository.default_branch }}"
    assert checkout["with"]["persist-credentials"] is False
