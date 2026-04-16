"""Tests for birkin.eval — dataset, runner, storage."""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin.eval.dataset import EvalCase, EvalDataset
from birkin.eval.runner import EvalRunner
from birkin.eval.storage import EvalStorage

# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


class TestEvalDataset:
    def test_create_dataset(self) -> None:
        ds = EvalDataset(
            name="test",
            cases=[
                EvalCase(input={"question": "What is 2+2?"}, expected_output="4"),
                EvalCase(input={"question": "Capital of Korea?"}, expected_output="Seoul"),
            ],
        )
        assert len(ds.cases) == 2
        assert ds.name == "test"

    def test_jsonl_roundtrip(self, tmp_path: Path) -> None:
        ds = EvalDataset(
            name="roundtrip",
            cases=[
                EvalCase(id="c1", input={"q": "hello"}, expected_output="hi", tags=["greet"]),
                EvalCase(id="c2", input={"q": "bye"}, expected_output="goodbye"),
            ],
        )
        path = tmp_path / "test.jsonl"
        ds.to_jsonl(path)
        assert path.is_file()

        loaded = EvalDataset.from_jsonl(path)
        assert loaded.name == "test"
        assert len(loaded.cases) == 2
        assert loaded.cases[0].id == "c1"
        assert loaded.cases[0].tags == ["greet"]

    def test_from_jsonl_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        ds = EvalDataset.from_jsonl(path)
        assert len(ds.cases) == 0


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class TestEvalRunner:
    @pytest.mark.asyncio
    async def test_run_case_success(self) -> None:
        async def mock_target(input_data: dict) -> dict:
            return {"output": "answer", "tokens_in": 10, "tokens_out": 20, "cost_usd": 0.001}

        runner = EvalRunner("mock-provider", mock_target)
        case = EvalCase(id="c1", input={"q": "test"})
        result = await runner.run_case(case)

        assert result.case_id == "c1"
        assert result.target == "mock-provider"
        assert result.output == "answer"
        assert result.tokens_in == 10
        assert result.tokens_out == 20
        assert result.error is None
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_run_case_error(self) -> None:
        async def failing_target(input_data: dict) -> dict:
            raise RuntimeError("provider down")

        runner = EvalRunner("bad-provider", failing_target)
        result = await runner.run_case(EvalCase(id="c1", input={}))

        assert result.error is not None
        assert "provider down" in result.error

    @pytest.mark.asyncio
    async def test_run_dataset(self) -> None:
        call_count = 0

        async def counting_target(input_data: dict) -> dict:
            nonlocal call_count
            call_count += 1
            return {"output": f"answer-{call_count}", "tokens_in": 5, "tokens_out": 10, "cost_usd": 0.001}

        ds = EvalDataset(
            name="count-test",
            cases=[EvalCase(input={"q": str(i)}) for i in range(3)],
        )
        runner = EvalRunner("test", counting_target)
        report = await runner.run_dataset(ds)

        assert report.dataset_name == "count-test"
        assert report.target == "test"
        assert len(report.results) == 3
        assert report.success_count == 3
        assert report.error_count == 0
        assert report.total_tokens == 45  # 3 * (5+10)
        assert report.avg_latency_ms >= 0


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


class TestEvalStorage:
    @pytest.mark.asyncio
    async def test_save_and_load(self, tmp_path: Path) -> None:
        storage = EvalStorage(tmp_path / "results")

        async def mock_target(input_data: dict) -> dict:
            return {"output": "ok", "tokens_in": 5, "tokens_out": 10, "cost_usd": 0.001}

        ds = EvalDataset(name="save-test", cases=[EvalCase(input={"q": "hi"})])
        runner = EvalRunner("provider-a", mock_target)
        report = await runner.run_dataset(ds)

        storage.save_report(report)
        loaded = storage.load_results("save-test")
        assert len(loaded) == 1
        assert loaded[0].target == "provider-a"

    def test_list_datasets(self, tmp_path: Path) -> None:
        storage = EvalStorage(tmp_path / "results")
        (tmp_path / "results" / "ds1.jsonl").write_text("", encoding="utf-8")
        (tmp_path / "results" / "ds2.jsonl").write_text("", encoding="utf-8")
        assert set(storage.list_datasets()) == {"ds1", "ds2"}

    def test_load_empty(self, tmp_path: Path) -> None:
        storage = EvalStorage(tmp_path / "results")
        assert storage.load_results("nonexistent") == []

    @pytest.mark.asyncio
    async def test_compare_runs(self, tmp_path: Path) -> None:
        storage = EvalStorage(tmp_path / "results")

        async def target_a(inp: dict) -> dict:
            return {"output": "a", "tokens_in": 10, "tokens_out": 20, "cost_usd": 0.01}

        async def target_b(inp: dict) -> dict:
            return {"output": "b", "tokens_in": 5, "tokens_out": 10, "cost_usd": 0.005}

        ds = EvalDataset(name="cmp", cases=[EvalCase(input={"q": "test"})])

        report_a = await EvalRunner("prov-a", target_a).run_dataset(ds)
        report_b = await EvalRunner("prov-b", target_b).run_dataset(ds)
        storage.save_report(report_a)
        storage.save_report(report_b)

        comparison = storage.compare_runs("cmp", "prov-a", "prov-b")
        assert comparison["target_a"]["name"] == "prov-a"
        assert comparison["target_b"]["name"] == "prov-b"
        assert comparison["target_a"]["total_cost"] > comparison["target_b"]["total_cost"]
