"""State graph engine — define graphs with nodes, edges, and conditional routing.

The StateGraph is the builder API. Call ``compile()`` to get a
CompiledGraph that can be executed via ``ainvoke`` or ``astream``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from birkin.core.graph.node import Event, EventType, FunctionNode, GraphNode, NodeResult
from birkin.core.graph.state import ContextSnapshot, GraphContext

logger = logging.getLogger(__name__)

# Sentinel for the graph's terminal node
END = "__end__"

# Maximum iterations for cycle detection
_MAX_ITERATIONS = 100


class Edge:
    """A simple directed edge from source to destination."""

    __slots__ = ("src", "dst")

    def __init__(self, src: str, dst: str) -> None:
        self.src = src
        self.dst = dst


class ConditionalEdge:
    """An edge that routes based on a function evaluating the context."""

    __slots__ = ("src", "router", "mapping")

    def __init__(
        self,
        src: str,
        router: Callable[[GraphContext], str],
        mapping: dict[str, str],
    ) -> None:
        self.src = src
        self.router = router
        self.mapping = mapping  # router_return_value -> node_name


class ParallelGroup:
    """A group of nodes to execute concurrently, joining at a target node."""

    __slots__ = ("nodes", "join_node")

    def __init__(self, nodes: list[str], join_node: str) -> None:
        self.nodes = nodes
        self.join_node = join_node


class StateGraph:
    """Builder for constructing a state graph.

    Usage::

        graph = StateGraph()
        graph.add_node(node_a)
        graph.add_node(node_b)
        graph.add_edge("a", "b")
        graph.set_entry("a")

        compiled = graph.compile()
        result = await compiled.ainvoke({"input": "hello"})
    """

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[Edge] = []
        self._conditional_edges: list[ConditionalEdge] = []
        self._parallel_groups: list[ParallelGroup] = []
        self._entry: str | None = None

    def add_node(self, node: GraphNode | Callable) -> StateGraph:
        """Add a node to the graph.

        Accepts either a GraphNode instance or an async function
        (auto-wrapped in FunctionNode using the function name).
        """
        if callable(node) and not isinstance(node, GraphNode):
            node = FunctionNode(node.__name__, node)
        self._nodes[node.name] = node
        return self

    def add_edge(self, src: str, dst: str) -> StateGraph:
        """Add a directed edge from src to dst."""
        self._edges.append(Edge(src, dst))
        return self

    def add_conditional_edge(
        self,
        src: str,
        router: Callable[[GraphContext], str],
        mapping: dict[str, str],
    ) -> StateGraph:
        """Add a conditional edge that routes based on context.

        Args:
            src: Source node name.
            router: Function that inspects ctx and returns a key.
            mapping: Maps router return values to destination node names.
                     Use END as a destination to terminate.
        """
        self._conditional_edges.append(ConditionalEdge(src, router, mapping))
        return self

    def add_parallel(self, nodes: list[str], join: str) -> StateGraph:
        """Add a parallel fan-out group.

        All listed nodes run concurrently. When all complete,
        execution continues at the join node.
        """
        self._parallel_groups.append(ParallelGroup(nodes, join))
        return self

    def set_entry(self, node_name: str) -> StateGraph:
        """Set the entry point node."""
        self._entry = node_name
        return self

    def compile(self) -> CompiledGraph:
        """Validate and compile the graph into an executable form."""
        if self._entry is None:
            raise ValueError("No entry node set. Call set_entry() first.")
        if self._entry not in self._nodes:
            raise ValueError(f"Entry node {self._entry!r} not found in graph nodes.")

        # Build edge lookup: src -> dst
        edge_map: dict[str, str] = {}
        for edge in self._edges:
            edge_map[edge.src] = edge.dst

        # Build conditional edge lookup: src -> ConditionalEdge
        cond_map: dict[str, ConditionalEdge] = {}
        for ce in self._conditional_edges:
            cond_map[ce.src] = ce

        # Build parallel lookup: node -> ParallelGroup
        parallel_map: dict[str, ParallelGroup] = {}
        for pg in self._parallel_groups:
            for n in pg.nodes:
                parallel_map[n] = pg

        return CompiledGraph(
            nodes=dict(self._nodes),
            edge_map=edge_map,
            cond_map=cond_map,
            parallel_groups=list(self._parallel_groups),
            parallel_map=parallel_map,
            entry=self._entry,
        )


class CompiledGraph:
    """Executable graph produced by StateGraph.compile().

    Supports linear, conditional, parallel, and looping execution
    with optional checkpointing.
    """

    def __init__(
        self,
        *,
        nodes: dict[str, GraphNode],
        edge_map: dict[str, str],
        cond_map: dict[str, ConditionalEdge],
        parallel_groups: list[ParallelGroup],
        parallel_map: dict[str, ParallelGroup],
        entry: str,
    ) -> None:
        self._nodes = nodes
        self._edge_map = edge_map
        self._cond_map = cond_map
        self._parallel_groups = parallel_groups
        self._parallel_map = parallel_map
        self._entry = entry

    async def ainvoke(
        self,
        initial_state: dict[str, Any],
        *,
        max_iterations: int = _MAX_ITERATIONS,
        on_checkpoint: Optional[Callable[[ContextSnapshot], Any]] = None,
    ) -> dict[str, Any]:
        """Execute the graph and return the final state dict.

        Args:
            initial_state: Starting state.
            max_iterations: Guard against infinite loops.
            on_checkpoint: Callback when a node requests checkpointing.

        Returns:
            The final state dict after graph execution.
        """
        events: list[Event] = []
        async for event in self.astream(
            initial_state,
            max_iterations=max_iterations,
            on_checkpoint=on_checkpoint,
        ):
            events.append(event)

        # Find the final state from the last node_end event
        for event in reversed(events):
            if event.type == EventType.NODE_END and "state" in event.data:
                return event.data["state"]

        return initial_state

    async def astream(
        self,
        initial_state: dict[str, Any],
        *,
        max_iterations: int = _MAX_ITERATIONS,
        on_checkpoint: Optional[Callable[[ContextSnapshot], Any]] = None,
    ):
        """Execute the graph, yielding events as they occur.

        Yields Event objects for node_start, node_end, errors, etc.
        """
        ctx = GraphContext(state=initial_state)
        current = self._entry
        iteration = 0

        while current != END and iteration < max_iterations:
            iteration += 1

            # Check if this node starts a parallel group
            if current in self._parallel_map:
                pg = self._parallel_map[current]
                # Only trigger parallel if current is the first node in the group
                if current == pg.nodes[0]:
                    async for event in self._run_parallel(pg, ctx, on_checkpoint):
                        yield event
                    current = pg.join_node
                    continue

            # Run single node
            node = self._nodes.get(current)
            if node is None:
                yield Event(type=EventType.NODE_ERROR, node_name=current, data={"error": f"Node not found: {current}"})
                break

            yield Event(type=EventType.NODE_START, node_name=current)

            try:
                result = await node.run(ctx)
            except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
                logger.error("Node %r failed: %s", current, exc)
                yield Event(type=EventType.NODE_ERROR, node_name=current, data={"error": str(exc)})
                break

            for event in result.emit_events:
                yield event

            yield Event(
                type=EventType.NODE_END,
                node_name=current,
                data={"state": dict(ctx.state)},
            )

            if result.checkpoint and on_checkpoint:
                snap = ctx.snapshot(current)
                on_checkpoint(snap)
                yield Event(type=EventType.CHECKPOINT, node_name=current)

            if result.error:
                yield Event(type=EventType.NODE_ERROR, node_name=current, data={"error": result.error})
                break

            # Determine next node
            current = self._resolve_next(current, result, ctx)

        if iteration >= max_iterations:
            logger.warning("Graph execution hit max iterations (%d)", max_iterations)

    def _resolve_next(self, current: str, result: NodeResult, ctx: GraphContext) -> str:
        """Determine the next node to execute."""
        # 1. Explicit next from node result
        if result.next_node is not None:
            return result.next_node

        # 2. Conditional edge
        if current in self._cond_map:
            ce = self._cond_map[current]
            key = ce.router(ctx)
            dst = ce.mapping.get(key, END)
            return dst

        # 3. Static edge
        if current in self._edge_map:
            return self._edge_map[current]

        # 4. No outgoing edge — end
        return END

    async def _run_parallel(
        self,
        group: ParallelGroup,
        ctx: GraphContext,
        on_checkpoint: Optional[Callable[[ContextSnapshot], Any]],
    ):
        """Execute a parallel group of nodes concurrently."""
        yield Event(
            type=EventType.PARALLEL_START,
            node_name=group.nodes[0],
            data={"parallel_nodes": group.nodes},
        )

        async def _run_one(node_name: str) -> tuple[str, NodeResult | None, str | None]:
            node = self._nodes.get(node_name)
            if node is None:
                return (node_name, None, f"Node not found: {node_name}")
            try:
                result = await node.run(ctx)
                return (node_name, result, None)
            except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
                return (node_name, None, str(exc))

        tasks = [_run_one(n) for n in group.nodes]
        results = await asyncio.gather(*tasks)

        for node_name, result, error in results:
            if error:
                yield Event(type=EventType.NODE_ERROR, node_name=node_name, data={"error": error})
            else:
                yield Event(type=EventType.NODE_END, node_name=node_name, data={"state": dict(ctx.state)})
                if result and result.checkpoint and on_checkpoint:
                    snap = ctx.snapshot(node_name)
                    on_checkpoint(snap)

        yield Event(
            type=EventType.PARALLEL_JOIN,
            node_name=group.join_node,
            data={"parallel_nodes": group.nodes},
        )
