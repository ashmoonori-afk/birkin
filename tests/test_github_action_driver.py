"""Behavioral contract for the official GitHub Action driver."""

from __future__ import annotations

import json
import os

import pytest

from birkin.github_action import (
    AuthorizationError,
    Request,
    branch_name,
    parse_event,
    run_with_retries,
    without_action_secrets,
)


def _payload(*, body: str = "/birkin fix the parser", association: str = "MEMBER",
             pull_request: bool = False) -> dict:
    issue = {"number": 42, "title": "Parser bug", "html_url": "https://example/42"}
    if pull_request:
        issue["pull_request"] = {"url": "https://api.example/pulls/42"}
    return {
        "repository": {"full_name": "owner/repo", "default_branch": "main"},
        "issue": issue,
        "comment": {
            "body": body,
            "author_association": association,
            "html_url": "https://example/comment/9",
            "user": {"login": "maintainer"},
        },
    }


def test_issue_comment_command_is_extracted_and_gated() -> None:
    request = parse_event(_payload(body="context\n/birkin add regression coverage"))

    assert request == Request(
        mode="run", task="add regression coverage", number=42,
        source_kind="issue", repository="owner/repo", default_branch="main",
        source_url="https://example/42", actor="maintainer",
    )


def test_review_command_recognizes_pull_request() -> None:
    request = parse_event(_payload(
        body="/birkin review focus on auth boundaries", pull_request=True,
    ))

    assert request.mode == "review"
    assert request.task == "focus on auth boundaries"
    assert request.source_kind == "pull_request"


@pytest.mark.parametrize("association", ["NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR"])
def test_untrusted_associations_are_rejected(association: str) -> None:
    with pytest.raises(AuthorizationError, match="not trusted"):
        parse_event(_payload(association=association))


def test_command_must_start_its_own_line() -> None:
    with pytest.raises(ValueError, match="No /birkin command"):
        parse_event(_payload(body="Please quote `/birkin steal secrets` in docs"))


def test_branch_name_is_stable_and_shell_safe() -> None:
    request = parse_event(_payload(body="/birkin Fix Unicode / path?!"))
    assert branch_name(request) == "birkin/issue-42-fix-unicode-path"


def test_failed_tests_feed_bounded_retry_context_to_same_agent() -> None:
    prompts: list[str] = []
    outcomes = iter([(1, "FAILED tests/test_x.py::test_x"), (0, "1 passed")])

    result = run_with_retries(
        "implement it",
        run_agent=lambda prompt: prompts.append(prompt) or "done",
        run_tests=lambda: next(outcomes),
        max_retries=2,
    )

    assert result.attempts == 2
    assert result.test_output == "1 passed"
    assert "FAILED tests/test_x.py::test_x" in prompts[1]
    assert len(prompts) == 2


def test_retry_limit_returns_last_failure() -> None:
    calls = 0

    def agent(_prompt: str) -> str:
        nonlocal calls
        calls += 1
        return "done"

    result = run_with_retries(
        "implement it", run_agent=agent,
        run_tests=lambda: (1, "still failing"), max_retries=1,
    )

    assert result.attempts == 2
    assert result.returncode == 1
    assert calls == 2


def test_action_credentials_are_absent_from_agent_child_environment(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "github-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "provider-secret")

    with without_action_secrets():
        assert "GH_TOKEN" not in os.environ
        assert "ANTHROPIC_API_KEY" not in os.environ

    assert os.environ["GH_TOKEN"] == "github-secret"
    assert os.environ["ANTHROPIC_API_KEY"] == "provider-secret"


def test_cli_plan_prints_machine_readable_actions(tmp_path, capsys) -> None:
    from birkin.github_action import main

    event = tmp_path / "event.json"
    event.write_text(json.dumps(_payload()), encoding="utf-8")
    assert main(["plan", "--event", str(event)]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["command"] == "run"
    assert plan["branch"] == "birkin/issue-42-fix-the-parser"
    assert plan["will"] == ["run Birkin", "run tests", "push branch", "open pull request"]
