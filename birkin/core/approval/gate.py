"""Approval gate — requires user approval before external actions."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ProposedAction(BaseModel, frozen=True):
    """An action that requires user approval before execution."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action_type: str  # "send_email", "delete_file", "api_call", etc.
    summary: str
    payload: dict[str, Any] = {}
    reversible: bool = True
    estimated_impact: Literal["low", "medium", "high"] = "medium"
    created_at: str = Field(default_factory=lambda: dt.datetime.now(dt.UTC).isoformat())


class ApprovalDecision(BaseModel):
    """User's decision on a proposed action."""

    approved: bool
    modified_payload: Optional[dict[str, Any]] = None
    user_note: Optional[str] = None
    decided_at: str = Field(default_factory=lambda: dt.datetime.now(dt.UTC).isoformat())


class ApprovalGate:
    """Manages pending approval requests.

    When the agent wants to perform an external action, it submits
    a ProposedAction. The gate holds it until the user approves,
    rejects, or it times out.

    Usage::

        gate = ApprovalGate()
        action = ProposedAction(action_type="send_email", summary="Send report to team")
        gate.submit(action)

        # User reviews via API
        gate.approve(action.id)
        # or gate.reject(action.id, note="Not now")

        decision = gate.get_decision(action.id)
    """

    def __init__(self) -> None:
        self._pending: dict[str, ProposedAction] = {}
        self._decisions: dict[str, ApprovalDecision] = {}

    def submit(self, action: ProposedAction) -> str:
        """Submit an action for approval. Returns the action ID."""
        self._pending[action.id] = action
        logger.info("Approval requested: [%s] %s", action.action_type, action.summary)
        return action.id

    def approve(self, action_id: str, *, modified_payload: Optional[dict] = None, note: Optional[str] = None) -> bool:
        """Approve a pending action. Returns True if found."""
        if action_id not in self._pending:
            return False
        self._decisions[action_id] = ApprovalDecision(
            approved=True,
            modified_payload=modified_payload,
            user_note=note,
        )
        del self._pending[action_id]
        logger.info("Action %s approved", action_id)
        return True

    def reject(self, action_id: str, *, note: Optional[str] = None) -> bool:
        """Reject a pending action. Returns True if found."""
        if action_id not in self._pending:
            return False
        self._decisions[action_id] = ApprovalDecision(approved=False, user_note=note)
        del self._pending[action_id]
        logger.info("Action %s rejected", action_id)
        return True

    def get_decision(self, action_id: str) -> Optional[ApprovalDecision]:
        """Get the decision for an action (None if still pending)."""
        return self._decisions.get(action_id)

    def is_pending(self, action_id: str) -> bool:
        """Check if an action is still waiting for approval."""
        return action_id in self._pending

    def list_pending(self) -> list[ProposedAction]:
        """Return all pending actions."""
        return list(self._pending.values())

    def list_decided(self) -> list[tuple[str, ApprovalDecision]]:
        """Return all decided actions."""
        return list(self._decisions.items())

    async def wait_for_decision(self, action_id: str, timeout_sec: int = 300) -> Optional[ApprovalDecision]:
        """Wait asynchronously for a decision on an action.

        Args:
            action_id: The action to wait for.
            timeout_sec: Max seconds to wait.

        Returns:
            ApprovalDecision if decided, None on timeout.
        """
        elapsed = 0
        poll_interval = 1
        while elapsed < timeout_sec:
            decision = self._decisions.get(action_id)
            if decision is not None:
                return decision
            if action_id not in self._pending:
                return None  # action was removed
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        # Timeout — auto-reject
        self.reject(action_id, note="Timed out waiting for approval")
        return self._decisions.get(action_id)

    def __len__(self) -> int:
        return len(self._pending)
