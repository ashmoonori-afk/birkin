"""Graph execution context — mutable shared state passed between nodes.

Uses the B model: mutable shared context with per-node transactional
checkpoints. Chosen because single-user/single-device environment,
diverse external LLM response shapes make reducer design costly,
and fast iteration is the priority.
"""

from __future__ import annotations

import copy
import datetime as dt
from typing import Any, Optional

from pydantic import BaseModel


class ContextSnapshot(BaseModel):
    """Immutable snapshot of GraphContext state for checkpointing."""

    state: dict[str, Any]
    node_name: str
    timestamp: str
    metadata: dict[str, Any] = {}


class GraphContext:
    """Mutable shared context passed through all nodes in a graph execution.

    Holds the state dict plus references to shared services (providers,
    memory, etc.) that nodes may need. Supports snapshot/restore for
    checkpointing.

    Usage::

        ctx = GraphContext(state={"input": "hello"})
        ctx.state["output"] = "world"
        snap = ctx.snapshot("node_a")
        ctx.restore(snap)
    """

    def __init__(
        self,
        state: Optional[dict[str, Any]] = None,
        *,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        self.state: dict[str, Any] = state or {}
        self.metadata: dict[str, Any] = metadata or {}

    def snapshot(self, node_name: str) -> ContextSnapshot:
        """Create an immutable snapshot of the current state."""
        return ContextSnapshot(
            state=copy.deepcopy(self.state),
            node_name=node_name,
            timestamp=dt.datetime.now(dt.timezone.utc).isoformat(),
            metadata=copy.deepcopy(self.metadata),
        )

    def restore(self, snapshot: ContextSnapshot) -> None:
        """Restore state from a snapshot."""
        self.state = copy.deepcopy(snapshot.state)
        self.metadata = copy.deepcopy(snapshot.metadata)

    def get(self, key: str, default: Any = None) -> Any:
        """Convenience accessor for state dict."""
        return self.state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Convenience setter for state dict."""
        self.state[key] = value

    def __repr__(self) -> str:
        keys = list(self.state.keys())
        return f"GraphContext(keys={keys})"
