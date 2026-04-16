"""Token budget manager — real-time tracking and enforcement during execution."""

from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel

from birkin.core.budget.policy import BudgetPolicy

logger = logging.getLogger(__name__)


class BudgetDecision(BaseModel):
    """Decision made by the budget manager before a provider call."""

    action: Literal["proceed", "compress_first", "downgrade", "abort"]
    suggested_model: Optional[str] = None
    reason: str = ""


class BudgetRemaining(BaseModel):
    """How much budget remains."""

    tokens: Optional[int] = None
    cost_usd: Optional[float] = None


class TokenBudget:
    """Real-time token/cost tracker injected into execution context.

    Checks before every provider call whether the budget allows it,
    and records usage after each call.

    Usage::

        budget = TokenBudget(policy)
        decision = budget.check_before_call(estimated_tokens=500)
        if decision.action == "proceed":
            # make the call
            budget.record_usage(tokens_in=100, tokens_out=400, cost_usd=0.01)
    """

    def __init__(self, policy: Optional[BudgetPolicy] = None) -> None:
        self._policy = policy or BudgetPolicy()
        self._used_tokens: int = 0
        self._used_cost_usd: float = 0.0
        self._node_tokens: int = 0  # reset per node

    @property
    def policy(self) -> BudgetPolicy:
        return self._policy

    @property
    def used_tokens(self) -> int:
        return self._used_tokens

    @property
    def used_cost_usd(self) -> float:
        return self._used_cost_usd

    def reset_node(self) -> None:
        """Reset per-node token counter (called at node start)."""
        self._node_tokens = 0

    def check_before_call(self, estimated_tokens: int = 0) -> BudgetDecision:
        """Check if the budget allows the next call.

        Args:
            estimated_tokens: Estimated tokens the call will consume.

        Returns:
            BudgetDecision indicating what action to take.
        """
        policy = self._policy

        # Check node-level budget
        if self._node_tokens + estimated_tokens > policy.max_tokens_per_node:
            if policy.on_node_exceeded == "compress":
                return BudgetDecision(
                    action="compress_first",
                    reason=f"Node budget would exceed {policy.max_tokens_per_node} tokens",
                )
            elif policy.on_node_exceeded == "downgrade":
                suggested = self._next_downgrade()
                return BudgetDecision(
                    action="downgrade",
                    suggested_model=suggested,
                    reason=f"Node budget exceeded, downgrading to {suggested}",
                )
            elif policy.on_node_exceeded == "stop":
                return BudgetDecision(action="abort", reason="Node token budget exceeded")
            # "warn" falls through to proceed

        # Check workflow-level budget
        if policy.max_tokens_per_workflow is not None:
            if self._used_tokens + estimated_tokens > policy.max_tokens_per_workflow:
                if policy.on_workflow_exceeded == "stop":
                    return BudgetDecision(action="abort", reason="Workflow token budget exceeded")
                return BudgetDecision(action="abort", reason="Workflow budget exceeded, pausing")

        # Check session-level budget
        if policy.max_tokens_per_session is not None:
            if self._used_tokens + estimated_tokens > policy.max_tokens_per_session:
                return BudgetDecision(action="abort", reason="Session token budget exceeded")

        # Check cost cap
        if policy.max_cost_usd is not None:
            if self._used_cost_usd >= policy.max_cost_usd:
                return BudgetDecision(action="abort", reason=f"Cost cap ${policy.max_cost_usd} reached")

        return BudgetDecision(action="proceed")

    def record_usage(
        self,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        """Record token and cost usage after a call."""
        total = tokens_in + tokens_out
        self._used_tokens += total
        self._node_tokens += total
        self._used_cost_usd += cost_usd
        logger.debug(
            "Budget: +%d tokens (total: %d), +$%.4f (total: $%.4f)",
            total,
            self._used_tokens,
            cost_usd,
            self._used_cost_usd,
        )

    def remaining(self) -> BudgetRemaining:
        """Return remaining budget."""
        tokens_left = None
        if self._policy.max_tokens_per_workflow is not None:
            tokens_left = max(0, self._policy.max_tokens_per_workflow - self._used_tokens)
        elif self._policy.max_tokens_per_session is not None:
            tokens_left = max(0, self._policy.max_tokens_per_session - self._used_tokens)

        cost_left = None
        if self._policy.max_cost_usd is not None:
            cost_left = max(0.0, self._policy.max_cost_usd - self._used_cost_usd)

        return BudgetRemaining(tokens=tokens_left, cost_usd=cost_left)

    def _next_downgrade(self) -> Optional[str]:
        """Find the next model in the downgrade chain."""
        chain = self._policy.downgrade_chain
        if not chain:
            return None
        # Simple: return the last (cheapest) in chain
        return chain[-1]
