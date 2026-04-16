"""Tests for birkin.core.budget — policy, manager, decisions."""

from __future__ import annotations

from birkin.core.budget.manager import TokenBudget
from birkin.core.budget.policy import BudgetPolicy


class TestBudgetPolicy:
    def test_defaults(self) -> None:
        p = BudgetPolicy()
        assert p.max_tokens_per_node == 4000
        assert p.max_tokens_per_workflow is None
        assert p.max_cost_usd is None
        assert p.on_node_exceeded == "compress"

    def test_custom(self) -> None:
        p = BudgetPolicy(
            max_tokens_per_node=2000,
            max_tokens_per_workflow=10000,
            max_cost_usd=1.0,
            on_node_exceeded="downgrade",
        )
        assert p.max_tokens_per_node == 2000
        assert p.on_node_exceeded == "downgrade"

    def test_frozen(self) -> None:
        p = BudgetPolicy()
        try:
            p.max_tokens_per_node = 999
            assert False, "Should raise"
        except Exception:
            pass


class TestTokenBudget:
    def test_proceed_under_budget(self) -> None:
        budget = TokenBudget(BudgetPolicy(max_tokens_per_node=4000))
        d = budget.check_before_call(500)
        assert d.action == "proceed"

    def test_node_exceeded_compress(self) -> None:
        budget = TokenBudget(BudgetPolicy(max_tokens_per_node=1000, on_node_exceeded="compress"))
        d = budget.check_before_call(1500)
        assert d.action == "compress_first"

    def test_node_exceeded_downgrade(self) -> None:
        budget = TokenBudget(BudgetPolicy(max_tokens_per_node=1000, on_node_exceeded="downgrade"))
        d = budget.check_before_call(1500)
        assert d.action == "downgrade"
        assert d.suggested_model is not None

    def test_node_exceeded_stop(self) -> None:
        budget = TokenBudget(BudgetPolicy(max_tokens_per_node=1000, on_node_exceeded="stop"))
        d = budget.check_before_call(1500)
        assert d.action == "abort"

    def test_node_exceeded_warn(self) -> None:
        budget = TokenBudget(BudgetPolicy(max_tokens_per_node=1000, on_node_exceeded="warn"))
        d = budget.check_before_call(1500)
        assert d.action == "proceed"  # warn still proceeds

    def test_workflow_exceeded(self) -> None:
        budget = TokenBudget(BudgetPolicy(max_tokens_per_node=10000, max_tokens_per_workflow=5000))
        budget.record_usage(tokens_in=2000, tokens_out=2500)
        d = budget.check_before_call(1000)
        assert d.action == "abort"
        assert "Workflow" in d.reason

    def test_session_exceeded(self) -> None:
        budget = TokenBudget(BudgetPolicy(max_tokens_per_session=3000))
        budget.record_usage(tokens_in=1500, tokens_out=1500)
        d = budget.check_before_call(100)
        assert d.action == "abort"
        assert "Session" in d.reason

    def test_cost_cap(self) -> None:
        budget = TokenBudget(BudgetPolicy(max_cost_usd=0.50))
        budget.record_usage(cost_usd=0.51)
        d = budget.check_before_call(100)
        assert d.action == "abort"
        assert "Cost cap" in d.reason

    def test_record_usage(self) -> None:
        budget = TokenBudget()
        budget.record_usage(tokens_in=100, tokens_out=200, cost_usd=0.05)
        assert budget.used_tokens == 300
        assert budget.used_cost_usd == 0.05

        budget.record_usage(tokens_in=50, tokens_out=50, cost_usd=0.01)
        assert budget.used_tokens == 400
        assert abs(budget.used_cost_usd - 0.06) < 1e-9

    def test_remaining_with_workflow_budget(self) -> None:
        budget = TokenBudget(BudgetPolicy(max_tokens_per_workflow=10000, max_cost_usd=1.0))
        budget.record_usage(tokens_in=2000, tokens_out=1000, cost_usd=0.30)
        rem = budget.remaining()
        assert rem.tokens == 7000
        assert rem.cost_usd == 0.70

    def test_remaining_no_limits(self) -> None:
        budget = TokenBudget()
        rem = budget.remaining()
        assert rem.tokens is None
        assert rem.cost_usd is None

    def test_reset_node(self) -> None:
        budget = TokenBudget(BudgetPolicy(max_tokens_per_node=1000))
        budget.record_usage(tokens_in=500, tokens_out=400)
        d = budget.check_before_call(200)
        assert d.action == "compress_first"  # 900 + 200 > 1000

        budget.reset_node()
        d2 = budget.check_before_call(200)
        assert d2.action == "proceed"  # node counter reset
