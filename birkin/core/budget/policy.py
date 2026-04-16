"""Budget policy — configuration for token/cost limits and enforcement actions."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class BudgetPolicy(BaseModel, frozen=True):
    """Defines hard caps and enforcement actions for token usage.

    Attributes:
        max_tokens_per_node: Max tokens a single node/call can consume.
        max_tokens_per_workflow: Max tokens for an entire workflow run.
        max_tokens_per_session: Max tokens for an entire session.
        max_cost_usd: Hard cost cap in USD.
        on_node_exceeded: Action when a single node exceeds its budget.
        on_workflow_exceeded: Action when the workflow exceeds budget.
        downgrade_chain: Ordered list of models to downgrade through.
    """

    max_tokens_per_node: int = 4000
    max_tokens_per_workflow: Optional[int] = None
    max_tokens_per_session: Optional[int] = None
    max_cost_usd: Optional[float] = None

    on_node_exceeded: Literal["stop", "compress", "downgrade", "warn"] = "compress"
    on_workflow_exceeded: Literal["stop", "checkpoint_and_pause"] = "stop"

    downgrade_chain: list[str] = ["opus", "sonnet", "haiku"]
