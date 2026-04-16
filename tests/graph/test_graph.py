"""Tests for birkin.core.graph — engine, nodes, checkpoint."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from birkin.core.graph.checkpoints.sqlite import SQLiteCheckpointer
from birkin.core.graph.engine import END, StateGraph
from birkin.core.graph.node import EventType, FunctionNode, NodeResult
from birkin.core.graph.state import ContextSnapshot, GraphContext

# ---------------------------------------------------------------------------
# Helper nodes
# ---------------------------------------------------------------------------


async def increment(ctx: GraphContext) -> NodeResult:
    ctx.set("count", ctx.get("count", 0) + 1)
    return NodeResult()


async def double(ctx: GraphContext) -> NodeResult:
    ctx.set("count", ctx.get("count", 0) * 2)
    return NodeResult()


async def set_done(ctx: GraphContext) -> NodeResult:
    ctx.set("done", True)
    return NodeResult()


async def checkpoint_node(ctx: GraphContext) -> NodeResult:
    ctx.set("checkpointed", True)
    return NodeResult(checkpoint=True)


async def error_node(ctx: GraphContext) -> NodeResult:
    return NodeResult(error="something went wrong")


async def loop_guard(ctx: GraphContext) -> NodeResult:
    ctx.set("count", ctx.get("count", 0) + 1)
    return NodeResult()


# ---------------------------------------------------------------------------
# GraphContext tests
# ---------------------------------------------------------------------------


class TestGraphContext:
    def test_get_set(self) -> None:
        ctx = GraphContext()
        ctx.set("x", 42)
        assert ctx.get("x") == 42
        assert ctx.get("missing", "default") == "default"

    def test_snapshot_restore(self) -> None:
        ctx = GraphContext(state={"a": 1, "b": [1, 2]})
        snap = ctx.snapshot("node1")
        ctx.set("a", 999)
        ctx.state["b"].append(3)
        ctx.restore(snap)
        assert ctx.state == {"a": 1, "b": [1, 2]}

    def test_snapshot_is_deep_copy(self) -> None:
        ctx = GraphContext(state={"list": [1, 2]})
        snap = ctx.snapshot("n")
        ctx.state["list"].append(3)
        assert snap.state["list"] == [1, 2]


# ---------------------------------------------------------------------------
# Linear execution
# ---------------------------------------------------------------------------


class TestLinearGraph:
    @pytest.mark.asyncio
    async def test_two_nodes(self) -> None:
        graph = StateGraph()
        graph.add_node(FunctionNode("inc", increment))
        graph.add_node(FunctionNode("dbl", double))
        graph.add_edge("inc", "dbl")
        graph.add_edge("dbl", END)
        graph.set_entry("inc")

        result = await graph.compile().ainvoke({"count": 0})
        assert result["count"] == 2  # (0+1) * 2

    @pytest.mark.asyncio
    async def test_three_nodes(self) -> None:
        graph = StateGraph()
        graph.add_node(FunctionNode("a", increment))
        graph.add_node(FunctionNode("b", increment))
        graph.add_node(FunctionNode("c", set_done))
        graph.add_edge("a", "b")
        graph.add_edge("b", "c")
        graph.add_edge("c", END)
        graph.set_entry("a")

        result = await graph.compile().ainvoke({"count": 0})
        assert result["count"] == 2
        assert result["done"] is True

    @pytest.mark.asyncio
    async def test_no_outgoing_edge_ends(self) -> None:
        graph = StateGraph()
        graph.add_node(FunctionNode("only", set_done))
        graph.set_entry("only")

        result = await graph.compile().ainvoke({})
        assert result["done"] is True


# ---------------------------------------------------------------------------
# Conditional branching
# ---------------------------------------------------------------------------


class TestConditionalGraph:
    @pytest.mark.asyncio
    async def test_branch_a(self) -> None:
        async def router(ctx: GraphContext) -> NodeResult:
            return NodeResult()

        async def path_a(ctx: GraphContext) -> NodeResult:
            ctx.set("path", "a")
            return NodeResult()

        async def path_b(ctx: GraphContext) -> NodeResult:
            ctx.set("path", "b")
            return NodeResult()

        graph = StateGraph()
        graph.add_node(FunctionNode("router", router))
        graph.add_node(FunctionNode("pa", path_a))
        graph.add_node(FunctionNode("pb", path_b))
        graph.set_entry("router")
        graph.add_conditional_edge(
            "router",
            lambda ctx: "go_a" if ctx.get("choice") == "a" else "go_b",
            {"go_a": "pa", "go_b": "pb"},
        )
        graph.add_edge("pa", END)
        graph.add_edge("pb", END)

        compiled = graph.compile()
        r = await compiled.ainvoke({"choice": "a"})
        assert r["path"] == "a"

        r = await compiled.ainvoke({"choice": "b"})
        assert r["path"] == "b"


# ---------------------------------------------------------------------------
# Loop with guard
# ---------------------------------------------------------------------------


class TestLoopGraph:
    @pytest.mark.asyncio
    async def test_loop_until_threshold(self) -> None:
        graph = StateGraph()
        graph.add_node(FunctionNode("loop", loop_guard))
        graph.set_entry("loop")
        graph.add_conditional_edge(
            "loop",
            lambda ctx: "continue" if ctx.get("count", 0) < 5 else "done",
            {"continue": "loop", "done": END},
        )

        result = await graph.compile().ainvoke({"count": 0})
        assert result["count"] == 5

    @pytest.mark.asyncio
    async def test_max_iterations_guard(self) -> None:
        graph = StateGraph()
        graph.add_node(FunctionNode("inf", increment))
        graph.add_edge("inf", "inf")
        graph.set_entry("inf")

        result = await graph.compile().ainvoke({"count": 0}, max_iterations=10)
        assert result["count"] == 10


# ---------------------------------------------------------------------------
# Parallel execution
# ---------------------------------------------------------------------------


class TestParallelGraph:
    @pytest.mark.asyncio
    async def test_parallel_fanout(self) -> None:
        async def worker_a(ctx: GraphContext) -> NodeResult:
            ctx.set("a_done", True)
            return NodeResult()

        async def worker_b(ctx: GraphContext) -> NodeResult:
            ctx.set("b_done", True)
            return NodeResult()

        async def join(ctx: GraphContext) -> NodeResult:
            ctx.set("joined", True)
            return NodeResult()

        graph = StateGraph()
        graph.add_node(FunctionNode("wa", worker_a))
        graph.add_node(FunctionNode("wb", worker_b))
        graph.add_node(FunctionNode("join", join))
        graph.add_parallel(["wa", "wb"], join="join")
        graph.add_edge("join", END)
        graph.set_entry("wa")

        result = await graph.compile().ainvoke({})
        assert result["a_done"] is True
        assert result["b_done"] is True
        assert result["joined"] is True


# ---------------------------------------------------------------------------
# Events / streaming
# ---------------------------------------------------------------------------


class TestGraphStreaming:
    @pytest.mark.asyncio
    async def test_events_emitted(self) -> None:
        graph = StateGraph()
        graph.add_node(FunctionNode("a", increment))
        graph.add_edge("a", END)
        graph.set_entry("a")

        events = []
        async for event in graph.compile().astream({"count": 0}):
            events.append(event)

        types = [e.type for e in events]
        assert EventType.NODE_START in types
        assert EventType.NODE_END in types

    @pytest.mark.asyncio
    async def test_error_event(self) -> None:
        graph = StateGraph()
        graph.add_node(FunctionNode("err", error_node))
        graph.set_entry("err")

        events = []
        async for event in graph.compile().astream({}):
            events.append(event)

        assert any(e.type == EventType.NODE_ERROR for e in events)


# ---------------------------------------------------------------------------
# Checkpoint integration
# ---------------------------------------------------------------------------


class TestGraphCheckpoint:
    @pytest.mark.asyncio
    async def test_checkpoint_callback(self) -> None:
        graph = StateGraph()
        graph.add_node(FunctionNode("cp", checkpoint_node))
        graph.add_edge("cp", END)
        graph.set_entry("cp")

        snapshots: list[ContextSnapshot] = []
        await graph.compile().ainvoke(
            {"data": "test"},
            on_checkpoint=lambda s: snapshots.append(s),
        )
        assert len(snapshots) == 1
        assert snapshots[0].state["checkpointed"] is True

    @pytest.mark.asyncio
    async def test_sqlite_checkpointer_roundtrip(self) -> None:

        db = Path(tempfile.mkdtemp()) / "test.db"
        cp = SQLiteCheckpointer(db)

        graph = StateGraph()
        graph.add_node(FunctionNode("cp", checkpoint_node))
        graph.add_edge("cp", END)
        graph.set_entry("cp")

        saved_snaps: list[ContextSnapshot] = []

        def save_sync(snap: ContextSnapshot) -> None:
            saved_snaps.append(snap)

        await graph.compile().ainvoke(
            {"value": 42},
            on_checkpoint=save_sync,
        )

        # Save collected snapshots to SQLite
        for snap in saved_snaps:
            await cp.save("thread-1", snap)

        metas = await cp.list_thread("thread-1")
        assert len(metas) >= 1

        loaded = await cp.load(metas[0].checkpoint_id)
        assert loaded.state["checkpointed"] is True
        assert loaded.state["value"] == 42
        cp.close()


# ---------------------------------------------------------------------------
# Compile validation
# ---------------------------------------------------------------------------


class TestCompileValidation:
    def test_no_entry_raises(self) -> None:
        graph = StateGraph()
        graph.add_node(FunctionNode("a", increment))
        with pytest.raises(ValueError, match="No entry node"):
            graph.compile()

    def test_invalid_entry_raises(self) -> None:
        graph = StateGraph()
        graph.add_node(FunctionNode("a", increment))
        graph.set_entry("nonexistent")
        with pytest.raises(ValueError, match="not found"):
            graph.compile()
