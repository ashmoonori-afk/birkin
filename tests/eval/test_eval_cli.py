"""Tests for birkin.eval.cli — eval run, list, diff commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from birkin.eval.cli import cmd_eval_diff, cmd_eval_list, cmd_eval_run
from birkin.eval.dataset import EvalCase, EvalDataset
from birkin.eval.runner import EvalResult
from birkin.eval.storage import EvalStorage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_dataset(path: Path, cases: list[EvalCase]) -> Path:
    """Write a small dataset JSONL for testing."""
    ds = EvalDataset(name=path.stem, cases=cases)
    ds.to_jsonl(path)
    return path


def _write_results(path: Path, results: list[EvalResult]) -> Path:
    """Write eval results as JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [r.model_dump_json() for r in results]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# cmd_eval_run
# ---------------------------------------------------------------------------


class TestCmdEvalRun:
    @pytest.mark.asyncio
    async def test_run_with_mock_provider(self, tmp_path: Path) -> None:
        ds_path = _write_dataset(
            tmp_path / "test.jsonl",
            [
                EvalCase(id="r1", input={"prompt": "hi"}),
                EvalCase(id="r2", input={"prompt": "bye"}),
            ],
        )
        output_dir = tmp_path / "out"

        # Mock provider
        mock_provider = AsyncMock()
        mock_provider.name = "mock"
        mock_provider.model = "test-model"

        mock_response = AsyncMock()
        mock_response.content = "hello"
        mock_response.usage = AsyncMock()
        mock_response.usage.prompt_tokens = 5
        mock_response.usage.completion_tokens = 10
        mock_provider.acomplete = AsyncMock(return_value=mock_response)

        with patch("birkin.eval.cli.create_provider", return_value=mock_provider):
            report = await cmd_eval_run(
                dataset_path=str(ds_path),
                provider_name="mock",
                output_dir=str(output_dir),
            )

        assert report.success_count == 2
        assert report.error_count == 0
        assert len(report.results) == 2

        # Verify results were saved
        storage = EvalStorage(output_dir)
        saved = storage.load_results("test")
        assert len(saved) == 2

    @pytest.mark.asyncio
    async def test_run_missing_dataset(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            await cmd_eval_run(
                dataset_path=str(tmp_path / "nonexistent.jsonl"),
                provider_name="anthropic",
            )


# ---------------------------------------------------------------------------
# cmd_eval_list
# ---------------------------------------------------------------------------


class TestCmdEvalList:
    def test_list_shows_results(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        r = EvalResult(case_id="c1", target="t", output="ok", latency_ms=100)
        (results_dir / "dataset-a.jsonl").write_text(r.model_dump_json() + "\n", encoding="utf-8")
        (results_dir / "dataset-b.jsonl").write_text(r.model_dump_json() + "\n", encoding="utf-8")

        datasets = cmd_eval_list(output_dir=str(results_dir))
        assert set(datasets) == {"dataset-a", "dataset-b"}

    def test_list_empty(self, tmp_path: Path) -> None:
        datasets = cmd_eval_list(output_dir=str(tmp_path / "empty"))
        assert datasets == []


# ---------------------------------------------------------------------------
# cmd_eval_diff
# ---------------------------------------------------------------------------


class TestCmdEvalDiff:
    def test_diff_computes_correct_deltas(self, tmp_path: Path) -> None:
        base_results = [
            EvalResult(
                case_id="c1",
                target="a",
                output="x",
                latency_ms=100,
                tokens_in=10,
                tokens_out=20,
            ),
            EvalResult(
                case_id="c2",
                target="a",
                output="y",
                latency_ms=200,
                tokens_in=15,
                tokens_out=25,
            ),
        ]
        curr_results = [
            EvalResult(
                case_id="c1",
                target="b",
                output="x2",
                latency_ms=80,
                tokens_in=8,
                tokens_out=18,
            ),
            EvalResult(
                case_id="c2",
                target="b",
                output="y2",
                latency_ms=250,
                tokens_in=20,
                tokens_out=30,
            ),
        ]

        base_path = _write_results(tmp_path / "base.jsonl", base_results)
        curr_path = _write_results(tmp_path / "curr.jsonl", curr_results)

        deltas = cmd_eval_diff(str(base_path), str(curr_path))

        assert deltas["c1"]["latency_delta_ms"] == -20  # 80 - 100
        assert deltas["c1"]["token_delta"] == -4  # (8+18) - (10+20)
        assert deltas["c2"]["latency_delta_ms"] == 50  # 250 - 200
        assert deltas["c2"]["token_delta"] == 10  # (20+30) - (15+25)

    def test_diff_handles_new_and_removed(self, tmp_path: Path) -> None:
        base_results = [
            EvalResult(case_id="c1", target="a", output="x", latency_ms=100),
        ]
        curr_results = [
            EvalResult(case_id="c2", target="b", output="y", latency_ms=200),
        ]

        base_path = _write_results(tmp_path / "base.jsonl", base_results)
        curr_path = _write_results(tmp_path / "curr.jsonl", curr_results)

        deltas = cmd_eval_diff(str(base_path), str(curr_path))

        assert deltas["c1"]["status_change"] == "REMOVED"
        assert deltas["c2"]["status_change"] == "NEW"

    def test_diff_status_change_detection(self, tmp_path: Path) -> None:
        base_results = [
            EvalResult(case_id="c1", target="a", output="ok", latency_ms=100),
        ]
        curr_results = [
            EvalResult(
                case_id="c1",
                target="b",
                latency_ms=50,
                error="failed",
            ),
        ]

        base_path = _write_results(tmp_path / "base.jsonl", base_results)
        curr_path = _write_results(tmp_path / "curr.jsonl", curr_results)

        deltas = cmd_eval_diff(str(base_path), str(curr_path))
        assert deltas["c1"]["status_change"] == "OK -> ERR"

    def test_diff_missing_file(self, tmp_path: Path) -> None:
        real_file = _write_results(
            tmp_path / "real.jsonl",
            [EvalResult(case_id="c1", target="t")],
        )
        with pytest.raises(SystemExit):
            cmd_eval_diff(str(tmp_path / "ghost.jsonl"), str(real_file))
