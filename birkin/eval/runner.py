"""Evaluation runner — execute eval cases against providers/workflows."""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel

from birkin.eval.dataset import EvalCase, EvalDataset

if TYPE_CHECKING:
    from birkin.memory.wiki import WikiMemory

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
    memory_used: bool = False


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

    def __init__(
        self,
        target_name: str,
        target_fn: Any,
        *,
        memory: Optional[WikiMemory] = None,
    ) -> None:
        self._target_name = target_name
        self._target_fn = target_fn
        self._memory = memory

    def _setup_case_memory(self, case: EvalCase) -> Optional[WikiMemory]:
        """Create a fresh temporary WikiMemory and ingest case setup data.

        Returns the temporary WikiMemory if the case has ``memory_setup``,
        otherwise ``None``.  Caller is responsible for cleaning up the
        temporary directory via ``shutil.rmtree(wiki.root)``.
        """
        if self._memory is None:
            return None

        memory_setup = case.input.get("memory_setup")
        if not memory_setup:
            return None

        from birkin.memory.wiki import WikiMemory

        tmp_dir = tempfile.mkdtemp(prefix="birkin_eval_mem_")
        wiki = WikiMemory(root=tmp_dir)
        wiki.init()

        # Ingest each page from memory_setup
        if isinstance(memory_setup, list):
            for page in memory_setup:
                wiki.ingest(
                    category=page.get("category", "concepts"),
                    slug=page.get("slug", "setup"),
                    content=page.get("content", ""),
                    tags=page.get("tags"),
                )
        elif isinstance(memory_setup, dict):
            wiki.ingest(
                category=memory_setup.get("category", "concepts"),
                slug=memory_setup.get("slug", "setup"),
                content=memory_setup.get("content", ""),
                tags=memory_setup.get("tags"),
            )

        return wiki

    async def run_case(self, case: EvalCase) -> EvalResult:
        """Run a single eval case.

        If memory is enabled and the case has ``memory_setup``, a fresh
        temporary WikiMemory is created, populated, and its context is
        prepended to the prompt.  The temp directory is cleaned up
        regardless of success or failure.
        """
        start = time.monotonic()
        case_wiki: Optional[WikiMemory] = None
        try:
            case_wiki = self._setup_case_memory(case)

            # Build input — optionally prepend memory context
            run_input = dict(case.input)
            memory_used = False
            if case_wiki is not None:
                memory_context = case_wiki.build_context()
                if memory_context:
                    prompt = run_input.get("prompt", "")
                    run_input["prompt"] = f"{memory_context}\n\n{prompt}"
                    memory_used = True

            response = await self._target_fn(run_input)
            elapsed_ms = int((time.monotonic() - start) * 1000)

            return EvalResult(
                case_id=case.id,
                target=self._target_name,
                output=response.get("output", ""),
                latency_ms=elapsed_ms,
                tokens_in=response.get("tokens_in", 0),
                tokens_out=response.get("tokens_out", 0),
                cost_usd=response.get("cost_usd", 0.0),
                memory_used=memory_used,
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
        finally:
            if case_wiki is not None:
                shutil.rmtree(case_wiki.root, ignore_errors=True)

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
