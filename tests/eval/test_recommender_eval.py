"""Test recommender evaluation harness."""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin.eval.recommender_eval import evaluate_recommender

_DATASET = Path(__file__).resolve().parent.parent.parent / "eval" / "datasets" / "recommender-quality-20.jsonl"


class TestRecommenderEval:
    @pytest.mark.asyncio
    async def test_eval_runs_without_error(self):
        if not _DATASET.exists():
            pytest.skip("dataset not found")
        result = await evaluate_recommender(_DATASET)
        assert result["total"] == 20
        assert "precision" in result
        assert "recall" in result

    @pytest.mark.asyncio
    async def test_precision_above_threshold(self):
        if not _DATASET.exists():
            pytest.skip("dataset not found")
        result = await evaluate_recommender(_DATASET)
        assert result["precision"] >= 0.7, f"Precision {result['precision']} below 0.7"

    @pytest.mark.asyncio
    async def test_recall_above_threshold(self):
        if not _DATASET.exists():
            pytest.skip("dataset not found")
        result = await evaluate_recommender(_DATASET)
        assert result["recall"] >= 0.7, f"Recall {result['recall']} below 0.7"
