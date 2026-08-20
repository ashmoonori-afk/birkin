"""Natural-language worker invocation.

Before this, only moirai could be reached from a natural-language turn, and only
to propose a *workflow*. The other implemented workers were CLI-only, so "run
the self-improvement pass" in chat reached nothing.

The door is the ``worker_invoke`` tool, deliberately shaped like
``companion_propose``: the model names a worker, Python validates the name, and
the request lands in the human approval queue. Python never classifies intent
with keywords — that design was built and deleted once already — and the tool
can never start a worker itself.
"""

from __future__ import annotations

import types

import pytest

from birkin import worker_call, worker_hooks
from birkin.tools import worker_tool


def _ctx(cfg: dict | None = None):
    return types.SimpleNamespace(cfg=cfg if cfg is not None else {"auto_approve": []})


def _tool_context(tmp_path, cfg: dict):
    from birkin.tools._types import ToolContext
    return ToolContext(cfg=cfg, client=None, cwd=tmp_path,
                       memory=None, depth=0, max_depth=0)


# -- the contract ----------------------------------------------------------

def test_invokable_workers_are_real_and_exclude_reserved_names() -> None:
    invokable = worker_call.invokable_workers()
    assert invokable, "no worker can be invoked from natural language"
    for name in invokable:
        assert name in worker_hooks.WORKERS
        assert name not in worker_hooks.RESERVED_WORKERS
    # osiris is declared but unimplemented; it must never be offered.
    assert "osiris" not in invokable


def test_resolve_accepts_a_real_worker_and_maps_it_to_its_command() -> None:
    call = worker_call.resolve("morpheus", "  tidy   the skills ")
    assert call.worker == "morpheus"
    assert call.task == "tidy the skills"          # whitespace collapsed
    assert call.argv() == ["birkin", "morpheus"]
    assert call.payload()["command"] == "morpheus"


def test_resolve_refuses_an_unknown_worker() -> None:
    with pytest.raises(worker_call.WorkerCallError, match="unknown worker"):
        worker_call.resolve("notaworker", "do it")


def test_resolve_refuses_a_reserved_worker() -> None:
    # osiris validates against WORKERS but has no implementation to run.
    with pytest.raises(worker_call.WorkerCallError, match="unknown worker"):
        worker_call.resolve("osiris", "do it")


@pytest.mark.parametrize("task", ["", "   ", "\n\t ", "x" * 5000, None, 7])
def test_resolve_refuses_an_empty_or_oversized_task(task) -> None:
    with pytest.raises(worker_call.WorkerCallError):
        worker_call.resolve("morpheus", task)


# -- the tool --------------------------------------------------------------

def test_the_tool_is_published_with_every_invokable_worker() -> None:
    tool = worker_tool.tools()[0]
    assert tool.name == "worker_invoke"
    enum = tool.input_schema["properties"]["worker"]["enum"]
    assert enum == list(worker_call.invokable_workers())
    assert "osiris" not in enum
    for name in worker_call.invokable_workers():
        assert name in tool.description


def test_the_tool_queues_an_approval_instead_of_running_anything(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import approvals

    seen: dict = {}

    def fake_propose(**kw):
        seen.update(kw)
        return {"auto": False, "id": "abc123"}

    monkeypatch.setattr(approvals, "propose", fake_propose)
    result = worker_tool.tools()[0].fn(
        {"worker": "morpheus", "task": "자기개선 한 번 돌려줘"}, _ctx())

    assert not result.is_error
    assert "approval" in result.content.lower()
    assert seen["origin"] == "morpheus"
    assert seen["payload"]["argv"] == ["birkin", "morpheus"]
    # Proposal-only: the tool must never claim it already ran.
    assert "queued" in result.content.lower()


def test_the_tool_reports_a_bad_worker_as_a_tool_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    result = worker_tool.tools()[0].fn({"worker": "osiris", "task": "go"}, _ctx())
    assert result.is_error
    assert "unknown worker" in result.content


def test_the_tool_is_registered_in_the_default_toolset(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import tools as tools_pkg

    ctx = _tool_context(tmp_path, {})
    groups = tools_pkg.build_tool_groups(ctx)
    names = [t.name for group in groups.values() for t in group]
    assert "worker_invoke" in names, "the model is never offered the worker door"


def test_the_tool_can_be_switched_off(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import tools as tools_pkg

    ctx = _tool_context(tmp_path, {"worker_call_auto": False})
    groups = tools_pkg.build_tool_groups(ctx)
    names = [t.name for group in groups.values() for t in group]
    assert "worker_invoke" not in names
