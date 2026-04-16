"""Evaluation storage — JSONL persistence for eval results."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from birkin.eval.runner import EvalReport, EvalResult

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path("eval_results")


class EvalStorage:
    """JSONL-based storage for evaluation results.

    Each eval run is appended to a file named after the dataset.

    Usage::

        storage = EvalStorage(Path("eval_results"))
        storage.save_report(report)
        results = storage.load_results("my-dataset")
    """

    def __init__(self, results_dir: Optional[Path] = None) -> None:
        self._dir = results_dir or _DEFAULT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def save_report(self, report: EvalReport) -> Path:
        """Save an eval report as JSONL (one line per result)."""
        file_path = self._dir / f"{report.dataset_name}.jsonl"
        with file_path.open("a", encoding="utf-8") as f:
            for result in report.results:
                f.write(result.model_dump_json() + "\n")
        logger.info("Saved %d results to %s", len(report.results), file_path)
        return file_path

    def load_results(self, dataset_name: str) -> list[EvalResult]:
        """Load all results for a dataset."""
        file_path = self._dir / f"{dataset_name}.jsonl"
        if not file_path.is_file():
            return []
        results: list[EvalResult] = []
        for line in file_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                results.append(EvalResult.model_validate_json(line))
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("Skipping malformed eval result: %s", exc)
        return results

    def list_datasets(self) -> list[str]:
        """Return dataset names with stored results."""
        return [p.stem for p in sorted(self._dir.glob("*.jsonl"))]

    def compare_runs(
        self,
        dataset_name: str,
        target_a: str,
        target_b: str,
    ) -> dict:
        """Compare results between two targets for regression detection."""
        results = self.load_results(dataset_name)
        a_results = [r for r in results if r.target == target_a]
        b_results = [r for r in results if r.target == target_b]

        def _avg(items: list[EvalResult], field: str) -> float:
            vals = [getattr(r, field) for r in items]
            return sum(vals) / len(vals) if vals else 0.0

        return {
            "dataset": dataset_name,
            "target_a": {
                "name": target_a,
                "count": len(a_results),
                "avg_latency_ms": _avg(a_results, "latency_ms"),
                "avg_tokens": _avg(a_results, "tokens_in") + _avg(a_results, "tokens_out"),
                "total_cost": sum(r.cost_usd for r in a_results),
                "error_rate": sum(1 for r in a_results if r.error) / len(a_results) if a_results else 0,
            },
            "target_b": {
                "name": target_b,
                "count": len(b_results),
                "avg_latency_ms": _avg(b_results, "latency_ms"),
                "avg_tokens": _avg(b_results, "tokens_in") + _avg(b_results, "tokens_out"),
                "total_cost": sum(r.cost_usd for r in b_results),
                "error_rate": sum(1 for r in b_results if r.error) / len(b_results) if b_results else 0,
            },
        }
