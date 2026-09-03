"""Structured natural-language worker invocation contract and executor tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import types
from typing import Any

import pytest

from birkin import worker_call, worker_executor, worker_hooks, worker_request
from birkin.tools import worker_tool


REQUEST_CASES = [
    pytest.param(
        {
            "worker": "moirai",
            "action": "run",
            "script": "hard-task",
            "task": "semantic-sentinel-moirai-task",
        },
        "semantic-sentinel-moirai-task",
        id="moirai",
    ),
    pytest.param(
        {"worker": "morpheus", "action": "run", "dry_run": True},
        "--dry-run",
        id="morpheus",
    ),
    pytest.param(
        {
            "worker": "harness",
            "action": "refine",
            "target": "semantic-sentinel-harness",
            "scope": "local",
        },
        "semantic-sentinel-harness",
        id="harness",
    ),
    pytest.param(
        {"worker": "odyssey", "goal": "semantic-sentinel-odyssey"},
        "semantic-sentinel-odyssey",
        id="odyssey",
    ),
    pytest.param(
        {
            "worker": "neurosis",
            "idea": "semantic-sentinel-neurosis",
            "resolution": "deep",
        },
        "semantic-sentinel-neurosis",
        id="neurosis",
    ),
    pytest.param(
        {
            "worker": "daedalus",
            "action": "note",
            "slug": "approved-map",
            "text": "semantic-sentinel-daedalus",
            "refs": ["a-approved"],
        },
        "semantic-sentinel-daedalus",
        id="daedalus",
    ),
]


def _ctx(cfg: dict[str, Any] | None = None) -> Any:
    return types.SimpleNamespace(cfg=cfg if cfg is not None else {"auto_approve": []})


def _tool_context(tmp_path: Any, cfg: dict[str, Any]) -> Any:
    from birkin.tools._types import ToolContext

    return ToolContext(
        cfg=cfg,
        client=None,
        cwd=tmp_path,
        memory=None,
        depth=0,
        max_depth=0,
    )


def test_invokable_workers_are_real_and_exclude_reserved_names() -> None:
    invokable = worker_call.invokable_workers()
    assert set(invokable) == {
        "moirai",
        "morpheus",
        "harness",
        "odyssey",
        "neurosis",
        "daedalus",
    }
    assert all(name in worker_hooks.WORKERS for name in invokable)
    assert not set(invokable) & set(worker_hooks.RESERVED_WORKERS)


def test_resolve_normalizes_a_typed_request_and_builds_discrete_argv() -> None:
    call = worker_call.resolve({"worker": "odyssey", "goal": "  ship   the feature "})
    assert call.request == worker_request.OdysseyRequest("ship the feature")
    assert call.argv()[-1] == "ship the feature"
    assert call.category == "worker"


@pytest.mark.parametrize(
    "worker_input",
    [
        {"worker": "osiris", "action": "run"},
        {"worker": "odyssey", "goal": ""},
        {"worker": "morpheus", "action": "run", "dry_run": "yes"},
        {"worker": "moirai", "action": "delete"},
        {"worker": "harness", "action": "rollback"},
        {"worker": "neurosis", "idea": "x", "resolution": "extreme"},
        {"worker": "daedalus", "action": "refresh", "slug": "x"},
        {"worker": "odyssey", "goal": "x", "command": "calc.exe"},
    ],
)
def test_malformed_structured_requests_fail_closed(
    worker_input: dict[str, Any],
) -> None:
    with pytest.raises(worker_call.WorkerCallError):
        worker_call.resolve(worker_input)


def test_tool_schema_discriminates_every_worker_action() -> None:
    schema = worker_tool.tools()[0].input_schema
    variants = schema["oneOf"]
    discriminators = {
        (
            variant["properties"]["worker"]["const"],
            variant["properties"].get("action", {}).get("const", ""),
        )
        for variant in variants
    }
    assert discriminators == {
        ("moirai", "run"),
        ("moirai", "list"),
        ("moirai", "status"),
        ("moirai", "resume"),
        ("morpheus", "run"),
        ("harness", "show"),
        ("harness", "history"),
        ("harness", "rollback"),
        ("harness", "export"),
        ("harness", "refine"),
        ("odyssey", ""),
        ("neurosis", ""),
        ("daedalus", "create"),
        ("daedalus", "refresh"),
        ("daedalus", "show"),
        ("daedalus", "note"),
        ("daedalus", "profile"),
    }
    assert all(variant["additionalProperties"] is False for variant in variants)


def test_tool_queues_a_digest_bound_manual_worker_approval(monkeypatch: Any) -> None:
    from birkin import approvals

    seen: dict[str, Any] = {}

    def fake_propose(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {"auto": False, "id": "abc123"}

    monkeypatch.setattr(approvals, "propose", fake_propose)
    request = {"worker": "morpheus", "action": "run", "dry_run": True}
    result = worker_tool.tools()[0].fn(
        request,
        _ctx({"auto_approve": ["shell"]}),
    )

    assert not result.is_error
    assert "queued" in str(result.content).lower()
    assert seen["category"] == "worker"
    assert seen["origin"] == "morpheus"
    payload = seen["payload"]
    canonical = json.dumps(
        payload["request"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    assert payload["digest"] == hashlib.sha256(canonical).hexdigest()


def test_tool_reports_a_bad_request_as_a_tool_error() -> None:
    result = worker_tool.tools()[0].fn({"worker": "osiris", "action": "run"}, _ctx())
    assert result.is_error
    assert "unknown worker" in str(result.content)


def test_tool_registration_can_be_disabled(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import tools as tools_pkg

    enabled = tools_pkg.build_tool_groups(_tool_context(tmp_path, {}))
    disabled = tools_pkg.build_tool_groups(
        _tool_context(tmp_path, {"worker_call_auto": False})
    )
    assert "worker_invoke" in [
        tool.name for group in enabled.values() for tool in group
    ]
    assert "worker_invoke" not in [
        tool.name for group in disabled.values() for tool in group
    ]


@pytest.mark.parametrize(("worker_input", "sentinel"), REQUEST_CASES)
def test_an_approved_worker_call_carries_semantic_input_to_argv(
    worker_input: dict[str, Any], sentinel: str, monkeypatch: Any
) -> None:
    """The six-worker RED pin: approved semantics reach argv, never a shell."""
    from birkin import approvals

    seen: dict[str, Any] = {}

    def fake_run(argv: tuple[str, ...], **kwargs: Any) -> Any:
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return types.SimpleNamespace(stdout="done", stderr="", returncode=0)

    monkeypatch.setattr(worker_executor.subprocess, "run", fake_run)
    call = worker_call.resolve(worker_input)
    result = approvals.execute_action(call.category, call.payload(), {})

    assert any(sentinel in argument for argument in seen["argv"])
    assert isinstance(seen["argv"], tuple)
    assert seen["kwargs"]["shell"] is False
    assert "[exit 0] done" == result


def test_moirai_hard_task_reaches_typed_script_args() -> None:
    sentinel = "hard-task-semantic-sentinel"
    call = worker_call.resolve(
        {
            "worker": "moirai",
            "action": "run",
            "script": "hard-task",
            "task": sentinel,
        }
    )

    command = call.argv()
    args_index = command.index("--args")
    assert json.loads(command[args_index + 1]) == {"task": sentinel}


def test_approval_digest_tampering_fails_before_subprocess(monkeypatch: Any) -> None:
    called = False

    def fake_run(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("must not execute")

    monkeypatch.setattr(worker_executor.subprocess, "run", fake_run)
    call = worker_call.resolve(
        {
            "worker": "moirai",
            "action": "run",
            "script": "hard-task",
            "task": "approved task",
        }
    )
    payload = call.payload()
    payload["request"] = {
        "worker": "moirai",
        "action": "run",
        "script": "hard-task",
        "task": "tampered task",
    }

    with pytest.raises(worker_request.WorkerRequestError, match="digest mismatch"):
        worker_executor.execute_approved(payload)
    assert called is False


@pytest.mark.parametrize("failure", ["nonzero", "timeout"])
def test_executor_raises_typed_error_for_process_failure(
    failure: str, monkeypatch: Any
) -> None:
    def fail_run(argv: tuple[str, ...], **kwargs: Any) -> Any:
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 3600)
        return types.SimpleNamespace(stdout="", stderr="failed", returncode=9)

    monkeypatch.setattr(worker_executor.subprocess, "run", fail_run)
    payload = worker_call.resolve(
        {"worker": "morpheus", "action": "run", "dry_run": True}
    ).payload()

    with pytest.raises(worker_executor.WorkerExecutionError):
        worker_executor.execute_approved(payload)
