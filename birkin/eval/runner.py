"""Evaluation runner — execute eval cases against providers/workflows."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from pydantic import BaseModel

from birkin.eval.dataset import EvalCase, EvalDataset

logger = logging.getLogger(__name__)


class EvalResult(BaseModel):
    """Result of evaluating a single case."""

    case_id: str
    target: str
    output: str = ""
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    judge_score: Optional[float] = None
    human_score: Optional[float] = None
    error: Optional[str] = None


class EvalReport(BaseModel):
    """Aggregated results from a dataset evaluation run."""

    dataset_name: str
    target: str
    results: list[EvalResult] = []
    total_latency_ms: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0
    success_count: int = 0
    error_count: int = 0


class EvalRunner:
    """Runs evaluation cases against a target (provider or workflow).

    The runner accepts a callable ``target_fn`` that takes an input dict
    and returns a response dict with 'output', 'tokens_in', 'tokens_out',
    'cost_usd' fields.

    Usage::

        async def my_target(input_data: dict) -> dict:
            response = await provider.acomplete(...)
            return {"output": response.content, "tokens_in": 100, ...}

        runner = EvalRunner("anthropic/sonnet", my_target)
        report = await runner.run_dataset(dataset)
    """

    def __init__(self, target_name: str, target_fn: Any) -> None:
        self._target_name = target_name
        self._target_fn = target_fn

    async def run_case(self, case: EvalCase) -> EvalResult:
        """Run a single eval case."""
        start = time.monotonic()
        try:
            response = await self._target_fn(case.input)
            elapsed_ms = int((time.monotonic() - start) * 1000)

            return EvalResult(
                case_id=case.id,
                target=self._target_name,
                output=response.get("output", ""),
                latency_ms=elapsed_ms,
                tokens_in=response.get("tokens_in", 0),
                tokens_out=response.get("tokens_out", 0),
                cost_usd=response.get("cost_usd", 0.0),
            )
        except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.error("Eval case %s failed: %s", case.id, exc)
            return EvalResult(
                case_id=case.id,
                target=self._target_name,
                latency_ms=elapsed_ms,
                error=str(exc),
            )

    async def run_dataset(self, dataset: EvalDataset) -> EvalReport:
        """Run all cases in a dataset sequentially."""
        results: list[EvalResult] = []
        for case in dataset.cases:
            result = await self.run_case(case)
            results.append(result)

        success_count = sum(1 for r in results if r.error is None)
        total_tokens = sum(r.tokens_in + r.tokens_out for r in results)
        total_latency = sum(r.latency_ms for r in results)
        total_cost = sum(r.cost_usd for r in results)

        return EvalReport(
            dataset_name=dataset.name,
            target=self._target_name,
            results=results,
            total_latency_ms=total_latency,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            avg_latency_ms=total_latency / len(results) if results else 0,
            success_count=success_count,
            error_count=len(results) - success_count,
        )
