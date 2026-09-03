"""Concurrent tool calls keep checkpoint timeline state invocation-local."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from birkin import checkpoints
from birkin.tools import Tool, ToolContext, ToolRegistry, ToolResult

_WORKERS = 8
_ROUNDS = 100


def test_missing_completion_token_is_an_idempotent_no_op(tmp_path: Path) -> None:
    # Given: a manager with no matching active invocation.
    manager = checkpoints.CheckpointManager(store_dir=tmp_path / "store")

    # When: the same missing token is completed repeatedly.
    manager.complete_tool("missing", failed=True)
    manager.complete_tool("missing", failed=False)

    # Then: no event is created and no error is raised.
    assert manager.timeline(tmp_path) == []


def test_same_name_tool_checkpoints_do_not_cross_contaminate(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    # Given: eight same-name tool calls overlap in every one of 100 rounds.
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    manager = checkpoints.CheckpointManager(store_dir=tmp_path / "store")
    context = ToolContext(cfg={"spill_threshold": 0}, client=None, cwd=tmp_path, checkpoints=manager)
    registry = ToolRegistry(context)
    local = threading.local()
    begin_release = [[threading.Event() for _ in range(_WORKERS)] for _ in range(_ROUNDS)]
    begin_done = [[threading.Event() for _ in range(_WORKERS)] for _ in range(_ROUNDS)]
    complete_release = [[threading.Event() for _ in range(_WORKERS)] for _ in range(_ROUNDS)]
    call_done = [[threading.Event() for _ in range(_WORKERS)] for _ in range(_ROUNDS)]
    handlers_ready = threading.Barrier(_WORKERS + 1, timeout=10)
    round_done = threading.Barrier(_WORKERS + 1, timeout=10)
    rows: list[dict[str, Any]] = []
    rows_lock = threading.Lock()

    def current_id() -> str:
        return f"{local.round_index}-{local.worker_index}"

    def ensure_checkpoint(*_args: Any, **_kwargs: Any) -> str:
        assert begin_release[local.round_index][local.worker_index].wait(timeout=10)
        return f"before-{current_id()}"

    def head(_workspace: Path) -> str:
        local.head_calls += 1
        if local.head_calls == 2:
            begin_done[local.round_index][local.worker_index].set()
        return f"head-{current_id()}"

    def take(*_args: Any, **_kwargs: Any) -> str:
        return f"after-{current_id()}"

    def append(_workspace: Path, _stream: str, row: dict[str, Any]) -> None:
        with rows_lock:
            rows.append(row)

    def execute(_tool_input: dict[str, Any], _context: ToolContext) -> ToolResult:
        handlers_ready.wait()
        assert complete_release[local.round_index][local.worker_index].wait(timeout=10)
        return ToolResult("ok")

    # The fabricated before/after hashes can never resolve, so the git diff in
    # complete_tool only adds process-spawn latency — seconds per call on
    # Windows, enough to blow the round barriers before any worker misbehaves.
    monkeypatch.setattr(checkpoints, "_run", lambda *_args, **_kwargs: (1, ""))
    monkeypatch.setattr(manager, "ensure_checkpoint", ensure_checkpoint)
    monkeypatch.setattr(manager, "_head", head)
    monkeypatch.setattr(manager, "_take", take)
    monkeypatch.setattr(manager._timeline, "append", append)
    registry.register(Tool("write_file", "test", {"type": "object"}, execute))
    results: list[ToolResult] = []

    def worker(worker_index: int) -> None:
        for round_index in range(_ROUNDS):
            local.worker_index = worker_index
            local.round_index = round_index
            local.head_calls = 0
            result = registry.execute(
                "write_file",
                {"path": f"{round_index}-{worker_index}.txt", "content": "changed"},
            )
            with rows_lock:
                results.append(result)
            call_done[round_index][worker_index].set()
            round_done.wait()

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(_WORKERS)]
    for thread in threads:
        thread.start()

    # When: beginnings and completions are ordered alike, forcing the old
    # name-based LIFO matcher to close a different invocation.
    for round_index in range(_ROUNDS):
        for worker_index in range(_WORKERS):
            begin_release[round_index][worker_index].set()
            assert begin_done[round_index][worker_index].wait(timeout=10)
        handlers_ready.wait()
        for worker_index in range(_WORKERS):
            complete_release[round_index][worker_index].set()
            assert call_done[round_index][worker_index].wait(timeout=10)
        round_done.wait()

    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    # Then: every call succeeds and each event owns both of its hashes.
    assert len(results) == _WORKERS * _ROUNDS
    assert all(not result.is_error for result in results), "no call may report Checkpoint failed"
    assert len(rows) == _WORKERS * _ROUNDS
    for row in rows:
        event_id = Path(row["touched"][0]).stem
        assert row["before"] == f"before-{event_id}"
        assert row["after"] == f"after-{event_id}"
