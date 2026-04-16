"""Checkpoint abstraction for graph state persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from birkin.core.graph.state import ContextSnapshot


class CheckpointMeta(BaseModel):
    """Metadata about a stored checkpoint."""

    checkpoint_id: str
    thread_id: str
    node_name: str
    timestamp: str


class Checkpointer(ABC):
    """Abstract base class for graph checkpoint storage."""

    @abstractmethod
    async def save(self, thread_id: str, snapshot: ContextSnapshot) -> str:
        """Save a snapshot. Returns the checkpoint ID."""
        ...

    @abstractmethod
    async def load(self, checkpoint_id: str) -> ContextSnapshot:
        """Load a snapshot by checkpoint ID."""
        ...

    @abstractmethod
    async def list_thread(self, thread_id: str) -> list[CheckpointMeta]:
        """List all checkpoints for a thread, ordered by timestamp."""
        ...
