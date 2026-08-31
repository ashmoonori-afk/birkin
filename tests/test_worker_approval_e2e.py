"""End-to-end worker tool -> durable approval -> argv executor coverage."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from birkin import (
    approval_execution,
    approvals,
    store,
    worker_executor,
    worker_request,
)
from birkin.tools import worker_tool
from tests.worker_approval_support import (
    FakeRunResult,
    FakeSubprocess,
    RunResult,
    context,
    mapping,
    text,
)


@pytest.mark.parametrize(
    ("worker_input", "sentinel"),
    [
        pytest.param(
            {
                "worker": "moirai",
                "action": "run",
                "script": "hard-task",
                "task": "approved-moirai-sentinel; &",
            },
            "approved-moirai-sentinel; &",
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
                "target": "approved-harness-sentinel",
                "scope": "local",
            },
            "approved-harness-sentinel",
            id="harness",
        ),
        pytest.param(
            {"worker": "odyssey", "goal": "approved-odyssey-sentinel; &"},
            "approved-odyssey-sentinel; &",
            id="odyssey",
        ),
        pytest.param(
            {
                "worker": "neurosis",
                "idea": "approved-neurosis-sentinel",
                "resolution": "deep",
            },
            "approved-neurosis-sentinel",
            id="neurosis",
        ),
        pytest.param(
            {
                "worker": "daedalus",
                "action": "note",
                "slug": "approved-map",
                "text": "approved-daedalus-sentinel",
                "refs": ["a-approved"],
            },
            "approved-daedalus-sentinel",
            id="daedalus",
        ),
    ],
)
def test_worker_request_waits_for_approval_then_executes_exact_argv(
    worker_input: worker_request.JsonObject,
    sentinel: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    seen_argv: list[tuple[str, ...]] = []
    seen_shell: list[bool] = []

    def fake_run(
        argv: tuple[str, ...],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
        shell: bool,
    ) -> RunResult:
        _ = capture_output, text, timeout, check
        seen_argv.append(argv)
        seen_shell.append(shell)
        return FakeRunResult(stdout="seeded", stderr="", returncode=0)

    identity_run = subprocess.run
    monkeypatch.setattr(worker_executor, "subprocess", FakeSubprocess(run=fake_run))
    proposed = worker_tool.tools()[0].fn(worker_input, context(tmp_path))

    assert subprocess.run is identity_run

    assert not proposed.is_error
    pending_records = store.list_pending()
    assert len(pending_records) == 1
    record = mapping(pending_records[0], "pending record")
    payload = mapping(record.get("payload"), "worker payload")
    assert record["category"] == "worker"
    assert payload["request"] == worker_input
    assert seen_argv == []

    approved = approval_execution.approve(text(record, "id"), approvals.execute_action)

    assert approved == {"ok": True, "result": "[exit 0] seeded"}
    assert any(sentinel in argument for argument in seen_argv[0])
    assert seen_shell == [False]
    resolved = store.get_pending(text(record, "id"))
    assert resolved is not None and resolved["status"] == "approved"
