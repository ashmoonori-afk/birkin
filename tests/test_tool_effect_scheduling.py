"""Trusted tool posture controls scheduling and checkpoint preflight."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from birkin import checkpoints, parallel
from birkin.agent import Agent
from birkin.tool_effects import (
    EffectSnapshot,
    NATIVE_TOOL_ORIGIN,
    ToolEffect,
    ToolOrigin,
)
from birkin.tools import Tool, ToolContext, ToolRegistry, ToolResult


PLUGIN_ORIGIN = ToolOrigin("plugin", "sample", "1.0.0", "a" * 64)


def _call(name: str, identifier: str) -> dict[str, Any]:
    return {"type": "tool_use", "id": identifier, "name": name, "input": {}}


def _agent(registry: Any, **kwargs: Any) -> Agent:
    return Agent(
        client=SimpleNamespace(provider="anthropic"),
        system="test",
        registry=registry,
        self_improve=False,
        **kwargs,
    )


class _Result:
    content = "ok"
    is_error = False


class _PostureRegistry:
    def __init__(self, parallel_safe: bool) -> None:
        self.parallel_safe = parallel_safe
        self.refreshes = 0
        self.calls: list[str] = []

    def specs(self) -> list[dict[str, Any]]:
        return []

    def refresh_effects(self) -> EffectSnapshot:
        self.refreshes += 1
        return EffectSnapshot("missing", ())

    def can_parallelize(self, name: str) -> bool:
        return self.parallel_safe

    def execute(self, name: str, tool_input: dict[str, Any]) -> _Result:
        self.calls.append(name)
        return _Result()


def _write_grant(home: Path, *, parallel_safe: bool) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "tool-effects.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "inspect_grants": [
                    {
                        "bundle_digest": "a" * 64,
                        "parallel_safe": parallel_safe,
                        "plugin": "sample",
                        "plugin_version": "1.0.0",
                        "reason": "reviewed for scheduling tests",
                        "recorded_at": "2026-08-21T12:00:00Z",
                        "tool": "plugin_read",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _plugin_registry(tmp_path: Path, handler: Any) -> ToolRegistry:
    registry = ToolRegistry(ToolContext(cfg={"spill_threshold": 0}, client=None, cwd=tmp_path))
    registry.register(Tool("plugin_read", "plugin read", {}, handler, origin=PLUGIN_ORIGIN))
    return registry


def test_unattested_plugin_tool_is_sequential(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    registry = _plugin_registry(tmp_path, lambda _input, _ctx: ToolResult("ok"))
    registry.refresh_effects()
    calls = [_call("plugin_read", "a"), _call("plugin_read", "b")]

    assert [kind for kind, _ in parallel.plan_segments(calls, registry.can_parallelize)] == [
        "sequential"
    ]


def test_inspect_grant_without_parallel_flag_is_sequential(
    tmp_path: Path, monkeypatch: Any
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    _write_grant(home, parallel_safe=False)
    registry = _plugin_registry(tmp_path, lambda _input, _ctx: ToolResult("ok"))
    registry.refresh_effects()
    calls = [_call("plugin_read", "a"), _call("plugin_read", "b")]

    assert [kind for kind, _ in parallel.plan_segments(calls, registry.can_parallelize)] == [
        "sequential"
    ]


def test_parallel_grant_lets_adjacent_calls_overlap(
    tmp_path: Path, monkeypatch: Any
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    _write_grant(home, parallel_safe=True)
    barrier = threading.Barrier(2, timeout=2)

    def handler(_input: dict[str, Any], _ctx: ToolContext) -> ToolResult:
        barrier.wait()
        return ToolResult("ok")

    registry = _plugin_registry(tmp_path, handler)
    results = _agent(registry)._run_tools(
        [_call("plugin_read", "first"), _call("plugin_read", "second")], None
    )

    assert [result["tool_use_id"] for result in results] == ["first", "second"]
    assert len(results) == 2


def test_effect_reload_applies_to_next_batch_not_mid_batch(
    tmp_path: Path, monkeypatch: Any
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    second_batch = threading.Barrier(2, timeout=2)
    parallel_phase = False
    first_batch_threads: list[int] = []

    def handler(_input: dict[str, Any], _ctx: ToolContext) -> ToolResult:
        nonlocal parallel_phase
        if parallel_phase:
            second_batch.wait()
        else:
            first_batch_threads.append(threading.get_ident())
            _write_grant(home, parallel_safe=True)
        return ToolResult("ok")

    registry = _plugin_registry(tmp_path, handler)
    agent = _agent(registry)
    calls = [_call("plugin_read", "a"), _call("plugin_read", "b")]
    coordinator = threading.get_ident()

    assert len(agent._run_tools(calls, None)) == 2
    assert first_batch_threads == [coordinator, coordinator]
    parallel_phase = True
    assert len(agent._run_tools(calls, None)) == 2


def test_registry_without_posture_method_parallelizes_legacy_safe_names() -> None:
    barrier = threading.Barrier(2, timeout=2)

    class Registry:
        def specs(self) -> list[dict[str, Any]]:
            return []

        def execute(self, name: str, tool_input: dict[str, Any]) -> _Result:
            barrier.wait()
            return _Result()

    results = _agent(Registry())._run_tools(
        [_call("web_fetch", "a"), _call("web_fetch", "b")], None
    )

    assert [result["tool_use_id"] for result in results] == ["a", "b"]
    assert [result["is_error"] for result in results] == [False, False]


def test_registry_posture_overrides_legacy_safe_name(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    coordinator = threading.get_ident()
    execution_threads: list[int] = []

    def handler(_input: dict[str, Any], _ctx: ToolContext) -> ToolResult:
        execution_threads.append(threading.get_ident())
        return ToolResult("ok")

    registry = ToolRegistry(
        ToolContext(cfg={"spill_threshold": 0}, client=None, cwd=tmp_path)
    )
    registry.register(
        Tool("web_fetch", "plugin fetch", {}, handler, origin=PLUGIN_ORIGIN)
    )
    results = _agent(registry)._run_tools(
        [_call("web_fetch", "a"), _call("web_fetch", "b")], None
    )

    assert registry.can_parallelize("web_fetch") is False
    assert execution_threads == [coordinator, coordinator]
    assert [result["tool_use_id"] for result in results] == ["a", "b"]


def test_raising_tool_yields_ordered_error_in_serial_and_parallel_batches() -> None:
    class Registry(_PostureRegistry):
        def execute(self, name: str, tool_input: dict[str, Any]) -> _Result:
            if name == "web_fetch":
                raise RuntimeError("network gone")
            return super().execute(name, tool_input)

    calls = [
        _call("read_file", "first"),
        _call("web_fetch", "middle"),
        _call("memory_search", "last"),
    ]
    for parallel_safe in (False, True):
        results = _agent(Registry(parallel_safe))._run_tools(calls, None)

        assert [result["tool_use_id"] for result in results] == [
            "first",
            "middle",
            "last",
        ]
        assert [result["is_error"] for result in results] == [False, True, False]
        assert "network gone" in results[1]["content"]


def test_malformed_snapshot_emits_one_normalized_warning() -> None:
    class Registry(_PostureRegistry):
        def refresh_effects(self) -> EffectSnapshot:
            self.refreshes += 1
            return EffectSnapshot("invalid", (), "invalid JSON at line 1 column 2")

    events: list[tuple[str, dict[str, Any]]] = []
    agent = _agent(Registry(False), on_event=lambda event, payload: events.append((event, payload)))

    agent._run_tools([_call("plugin_read", "a"), _call("plugin_read", "b")], None)

    warnings = [payload for event, payload in events if event == "warning"]
    assert warnings == [
        {"message": "Tool effect file error: invalid JSON at line 1 column 2."}
    ]


class _CheckpointSpy:
    enabled = True

    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []
        self.active: list[tuple[str, bool]] = []

    def _head(self, workspace: Path) -> str:
        return "head"

    def ensure_checkpoint(self, workspace: Path, reason: str = "") -> str:
        self.events.append(("checkpoint", reason))
        return "before"

    def begin_tool(
        self,
        workspace: Path,
        tool: str,
        tool_input: dict[str, Any],
        *,
        origin: ToolOrigin = NATIVE_TOOL_ORIGIN,
        effect: ToolEffect = ToolEffect.CHANGE,
    ) -> None:
        mutating = origin.kind == "plugin" and effect is ToolEffect.CHANGE
        if tool in {"write_file", "edit_file", "run_shell"} and origin.kind == "native":
            mutating = not bool(tool_input.get("_read_only"))
        if mutating:
            self.ensure_checkpoint(workspace, f"before {tool}")
        self.active.append((tool, mutating))
        self.events.append(("begin", dict(tool_input)))


def _ctx(tmp_path: Path, manager: Any) -> Any:
    return SimpleNamespace(cwd=tmp_path, checkpoints=manager, emit=None)


def test_external_change_checkpoints_before_handler(tmp_path: Path) -> None:
    manager = _CheckpointSpy()

    checkpoints.preflight(
        _ctx(tmp_path, manager),
        "plugin_write",
        {},
        origin=PLUGIN_ORIGIN,
        effect=ToolEffect.CHANGE,
    )
    manager.events.append(("handler", None))

    assert [event for event, _ in manager.events] == ["checkpoint", "begin", "handler"]


def test_external_inspect_skips_generic_checkpoint(tmp_path: Path) -> None:
    manager = _CheckpointSpy()

    checkpoints.preflight(
        _ctx(tmp_path, manager),
        "plugin_read",
        {},
        origin=PLUGIN_ORIGIN,
        effect=ToolEffect.INSPECT,
    )

    assert manager.events == [("begin", {})]
    assert manager.active == [("plugin_read", False)]


def test_native_file_checkpoint_behavior_is_unchanged(tmp_path: Path) -> None:
    project = tmp_path / "project"
    nested = project / "src"
    nested.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    manager = _CheckpointSpy()

    checkpoints.preflight(
        _ctx(nested, manager),
        "write_file",
        {"path": "module.py"},
        origin=NATIVE_TOOL_ORIGIN,
        effect=ToolEffect.CHANGE,
    )

    assert manager.events[0] == ("checkpoint", "before write_file")
    assert manager.active == [("write_file", True)]


def test_native_shell_read_refinement_is_unchanged(tmp_path: Path) -> None:
    manager = _CheckpointSpy()

    checkpoints.preflight(
        _ctx(tmp_path, manager),
        "run_shell",
        {"command": "pwd"},
        origin=NATIVE_TOOL_ORIGIN,
        effect=ToolEffect.CHANGE,
    )

    assert manager.events == [("begin", {"command": "pwd", "_read_only": True})]
    assert manager.active == [("run_shell", False)]


def test_failed_external_mutation_still_closes_timeline_event(
    tmp_path: Path, monkeypatch: Any
) -> None:
    manager = checkpoints.CheckpointManager(store_dir=tmp_path / "store")
    rows: list[dict[str, Any]] = []
    monkeypatch.setattr(manager, "ensure_checkpoint", lambda *_args, **_kwargs: "before")
    monkeypatch.setattr(manager, "_head", lambda _workspace: "before")
    monkeypatch.setattr(manager, "_take", lambda *_args, **_kwargs: "after")
    monkeypatch.setattr(manager._timeline, "append", lambda _w, _s, row: rows.append(row))

    token = manager.begin_tool(
        tmp_path,
        "plugin_write",
        {},
        origin=PLUGIN_ORIGIN,
        effect=ToolEffect.CHANGE,
    )
    manager.complete_tool(token, failed=True)

    assert manager._active_tools == {}
    assert len(rows) == 1
    assert rows[0]["tool"] == "plugin_write"
    assert rows[0]["status"] == "failed"


def test_blocked_pre_tool_hook_creates_no_checkpoint(tmp_path: Path) -> None:
    class Hooks:
        def pre_tool(self, name: str, tool_input: dict[str, Any]) -> str:
            return "blocked"

    manager = _CheckpointSpy()
    context = ToolContext(
        cfg={"spill_threshold": 0},
        client=None,
        cwd=tmp_path,
        checkpoints=manager,
        hooks=Hooks(),
    )
    registry = ToolRegistry(context)
    registry.register(
        Tool("write_file", "write", {}, lambda _input, _ctx: ToolResult("unexpected"))
    )

    result = registry.execute("write_file", {"path": "x"})

    assert result.is_error
    assert manager.events == []
