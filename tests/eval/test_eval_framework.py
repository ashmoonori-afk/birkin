"""Tests for birkin.eval framework — dataset round-trip, runner, storage."""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin.eval.dataset import EvalCase, EvalDataset
from birkin.eval.runner import EvalResult, EvalRunner
from birkin.eval.storage import EvalStorage

# ---------------------------------------------------------------------------
# Dataset round-trip
# ---------------------------------------------------------------------------


class TestEvalDatasetRoundtrip:
    """Verify JSONL serialisation preserves all fields."""

    def test_roundtrip_preserves_fields(self, tmp_path: Path) -> None:
        cases = [
            EvalCase(
                id="rt-1",
                input={"prompt": "Hello"},
                expected_output="Hi there",
                rubric=["polite", "concise"],
                tags=["greeting"],
            ),
            EvalCase(
                id="rt-2",
                input={"prompt": "Summarise X"},
                expected_output="X is ...",
                rubric=["accurate"],
                tags=["summarisation"],
            ),
        ]
        ds = EvalDataset(name="roundtrip-test", cases=cases)
        path = tmp_path / "rt.jsonl"
        ds.to_jsonl(path)

        loaded = EvalDataset.from_jsonl(path, name="roundtrip-test")
        assert len(loaded.cases) == 2
        assert loaded.cases[0].id == "rt-1"
        assert loaded.cases[0].input == {"prompt": "Hello"}
        assert loaded.cases[0].expected_output == "Hi there"
        assert loaded.cases[0].rubric == ["polite", "concise"]
        assert loaded.cases[0].tags == ["greeting"]

    def test_roundtrip_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        ds = EvalDataset.from_jsonl(path)
        assert ds.cases == []

    def test_roundtrip_blank_lines_skipped(self, tmp_path: Path) -> None:
        case = EvalCase(id="c1", input={"prompt": "test"})
        path = tmp_path / "blanks.jsonl"
        path.write_text(
            case.model_dump_json() + "\n\n\n" + case.model_dump_json() + "\n",
            encoding="utf-8",
        )
        ds = EvalDataset.from_jsonl(path)
        assert len(ds.cases) == 2


# ---------------------------------------------------------------------------
# Runner with mock target
# ---------------------------------------------------------------------------


class TestEvalRunnerMock:
    """Run eval cases against a mock async target function."""

    @pytest.mark.asyncio
    async def test_successful_run(self) -> None:
        async def mock_target(input_data: dict) -> dict:
            return {
                "output": f"echo: {input_data.get('prompt', '')}",
                "tokens_in": 10,
                "tokens_out": 20,
                "cost_usd": 0.001,
            }

        runner = EvalRunner("mock/echo", mock_target)
        case = EvalCase(id="m1", input={"prompt": "hi"})
        result = await runner.run_case(case)

        assert result.case_id == "m1"
        assert result.output == "echo: hi"
        assert result.error is None
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_error_captured(self) -> None:
        async def failing(input_data: dict) -> dict:
            raise RuntimeError("boom")

        runner = EvalRunner("bad", failing)
        result = await runner.run_case(EvalCase(id="e1", input={}))
        assert result.error is not None
        assert "boom" in result.error

    @pytest.mark.asyncio
    async def test_dataset_report_aggregates(self) -> None:
        async def target(input_data: dict) -> dict:
            return {"output": "ok", "tokens_in": 5, "tokens_out": 10, "cost_usd": 0.002}

        ds = EvalDataset(
            name="agg",
            cases=[EvalCase(input={"prompt": str(i)}) for i in range(4)],
        )
        report = await EvalRunner("t", target).run_dataset(ds)

        assert report.success_count == 4
        assert report.error_count == 0
        assert report.total_tokens == 60  # 4*(5+10)
        assert report.total_cost_usd == pytest.approx(0.008)


# ---------------------------------------------------------------------------
# Storage save / load
# ---------------------------------------------------------------------------


class TestEvalStoragePersistence:
    @pytest.mark.asyncio
    async def test_save_load_cycle(self, tmp_path: Path) -> None:
        storage = EvalStorage(tmp_path / "res")

        async def target(inp: dict) -> dict:
            return {"output": "v", "tokens_in": 1, "tokens_out": 2, "cost_usd": 0.0}

        ds = EvalDataset(name="persist", cases=[EvalCase(input={"prompt": "a"})])
        report = await EvalRunner("prov", target).run_dataset(ds)
        saved_path = storage.save_report(report)

        assert saved_path.is_file()
        loaded = storage.load_results("persist")
        assert len(loaded) == 1
        assert loaded[0].target == "prov"
        assert loaded[0].output == "v"

    def test_list_datasets(self, tmp_path: Path) -> None:
        storage = EvalStorage(tmp_path / "res")
        (tmp_path / "res" / "alpha.jsonl").write_text("", encoding="utf-8")
        (tmp_path / "res" / "beta.jsonl").write_text("", encoding="utf-8")
        names = storage.list_datasets()
        assert set(names) == {"alpha", "beta"}

    def test_load_missing_returns_empty(self, tmp_path: Path) -> None:
        storage = EvalStorage(tmp_path / "res")
        assert storage.load_results("nope") == []

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        storage = EvalStorage(tmp_path / "res")
        path = tmp_path / "res" / "bad.jsonl"
        good = EvalResult(case_id="g1", target="t").model_dump_json()
        path.write_text(good + "\n{bad json}\n", encoding="utf-8")
        results = storage.load_results("bad")
        assert len(results) == 1
        assert results[0].case_id == "g1"
