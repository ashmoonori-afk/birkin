"""Graph node protocol and result types.

Nodes are the execution units within a state graph. Each node receives
the shared GraphContext, performs work, and returns a NodeResult indicating
what to do next.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from birkin.core.graph.state import GraphContext


class EventType(str, Enum):
    """Types of events emitted during graph execution."""

    NODE_START = "node_start"
    NODE_END = "node_end"
    NODE_ERROR = "node_error"
    CHECKPOINT = "checkpoint"
    PARALLEL_START = "parallel_start"
    PARALLEL_JOIN = "parallel_join"


class Event(BaseModel):
    """Event emitted during graph execution for observability."""

    type: EventType
    node_name: str
    data: dict[str, Any] = {}


class NodeResult(BaseModel):
    """Result returned by a graph node after execution.

    Attributes:
        next_node: Explicit next node name. None lets the engine
                   decide via edges.
        emit_events: Events to emit for observability.
        checkpoint: Whether to save a checkpoint after this node.
        error: Error message if the node failed.
    """

    next_node: str | None = None
    emit_events: list[Event] = []
    checkpoint: bool = False
    error: str | None = None


@runtime_checkable
class GraphNode(Protocol):
    """Protocol for graph execution nodes.

    Any object with a ``name`` attribute and an async ``run`` method
    that accepts a GraphContext satisfies this protocol.
    """

    name: str

    async def run(self, ctx: GraphContext) -> NodeResult: ...


class FunctionNode:
    """Simple node that wraps an async function.

    Usage::

        async def my_logic(ctx: GraphContext) -> NodeResult:
            ctx.set("result", "done")
            return NodeResult()

        node = FunctionNode("my_node", my_logic)
    """

    def __init__(self, name: str, func: Any) -> None:
        self.name = name
        self._func = func

    async def run(self, ctx: GraphContext) -> NodeResult:
        return await self._func(ctx)

    def __repr__(self) -> str:
        return f"FunctionNode({self.name!r})"
