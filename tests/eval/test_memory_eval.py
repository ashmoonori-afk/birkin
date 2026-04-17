"""Tests for memory-aware eval — EvalRunner with WikiMemory integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from birkin.eval.dataset import EvalCase, EvalDataset
from birkin.eval.runner import EvalRunner
from birkin.memory.wiki import WikiMemory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_case_with_memory(case_id: str, prompt: str, setup: dict) -> EvalCase:
    """Create an EvalCase with memory_setup in its input."""
    return EvalCase(
        id=case_id,
        input={"prompt": prompt, "memory_setup": setup},
        tags=["memory"],
    )


def _make_memory_setup(slug: str = "test-page", content: str = "# Test\n\nHello world") -> dict:
    return {"category": "concepts", "slug": slug, "content": content}


async def _echo_target(input_data: dict) -> dict:
    """Target function that echoes the prompt as output."""
    return {
        "output": input_data.get("prompt", ""),
        "tokens_in": 10,
        "tokens_out": 20,
        "cost_usd": 0.001,
    }


# ---------------------------------------------------------------------------
# EvalRunner with memory
# ---------------------------------------------------------------------------


class TestEvalRunnerMemory:
    @pytest.mark.asyncio
    async def test_memory_injects_context_into_prompt(self, tmp_path: Path) -> None:
        """When memory is enabled and case has memory_setup, context is prepended."""
        wiki = WikiMemory(root=tmp_path / "mem")
        wiki.init()

        case = _make_case_with_memory(
            "m1",
            "What is the answer?",
            _make_memory_setup(content="# Knowledge\n\nThe answer is 42."),
        )

        runner = EvalRunner("test", _echo_target, memory=wiki)
        result = await runner.run_case(case)

        assert result.error is None
        assert result.memory_used is True
        # The output (echoed prompt) should contain both memory context and original prompt
        assert "The answer is 42" in result.output
        assert "What is the answer?" in result.output

    @pytest.mark.asyncio
    async def test_without_memory_no_context(self) -> None:
        """Without memory, the prompt is passed through unchanged."""
        case = EvalCase(id="no-mem", input={"prompt": "plain question"})

        runner = EvalRunner("test", _echo_target)
        result = await runner.run_case(case)

        assert result.error is None
        assert result.memory_used is False
        assert result.output == "plain question"

    @pytest.mark.asyncio
    async def test_memory_enabled_but_case_has_no_setup(self, tmp_path: Path) -> None:
        """Memory is enabled on runner but case lacks memory_setup — no injection."""
        wiki = WikiMemory(root=tmp_path / "mem")
        wiki.init()

        case = EvalCase(id="no-setup", input={"prompt": "just a question"})

        runner = EvalRunner("test", _echo_target, memory=wiki)
        result = await runner.run_case(case)

        assert result.error is None
        assert result.memory_used is False
        assert result.output == "just a question"

    @pytest.mark.asyncio
    async def test_memory_setup_ingested_correctly(self, tmp_path: Path) -> None:
        """Verify that memory_setup data is actually ingested into the wiki."""
        wiki = WikiMemory(root=tmp_path / "mem")
        wiki.init()

        content = "# Preferences\n\nLanguage: Rust\nEditor: Helix"
        case = _make_case_with_memory(
            "m2",
            "What language do I prefer?",
            {"category": "entities", "slug": "prefs", "content": content},
        )

        runner = EvalRunner("test", _echo_target, memory=wiki)
        result = await runner.run_case(case)

        assert result.error is None
        assert result.memory_used is True
        assert "Rust" in result.output

    @pytest.mark.asyncio
    async def test_memory_setup_list_format(self, tmp_path: Path) -> None:
        """memory_setup can be a list of pages to ingest."""
        wiki = WikiMemory(root=tmp_path / "mem")
        wiki.init()

        case = EvalCase(
            id="multi",
            input={
                "prompt": "Tell me about my setup",
                "memory_setup": [
                    {"category": "entities", "slug": "page-a", "content": "# Page A\n\nAlpha data"},
                    {"category": "concepts", "slug": "page-b", "content": "# Page B\n\nBeta data"},
                ],
            },
            tags=["memory"],
        )

        runner = EvalRunner("test", _echo_target, memory=wiki)
        result = await runner.run_case(case)

        assert result.error is None
        assert result.memory_used is True
        # Both pages should appear in context
        assert "Alpha data" in result.output
        assert "Beta data" in result.output

    @pytest.mark.asyncio
    async def test_temp_wiki_isolated_between_cases(self, tmp_path: Path) -> None:
        """Each case gets a fresh temp wiki — no cross-contamination."""
        wiki = WikiMemory(root=tmp_path / "mem")
        wiki.init()

        case_a = _make_case_with_memory(
            "iso-a",
            "What is secret A?",
            _make_memory_setup(slug="secret-a", content="# Secret A\n\nAlpha secret value"),
        )
        case_b = _make_case_with_memory(
            "iso-b",
            "What is secret B?",
            _make_memory_setup(slug="secret-b", content="# Secret B\n\nBeta secret value"),
        )

        runner = EvalRunner("test", _echo_target, memory=wiki)

        result_a = await runner.run_case(case_a)
        result_b = await runner.run_case(case_b)

        # Case A output should NOT contain case B data
        assert "Alpha secret" in result_a.output
        assert "Beta secret" not in result_a.output

        # Case B output should NOT contain case A data
        assert "Beta secret" in result_b.output
        assert "Alpha secret" not in result_b.output

    @pytest.mark.asyncio
    async def test_memory_used_field_in_result(self, tmp_path: Path) -> None:
        """EvalResult.memory_used reflects whether memory was actually injected."""
        wiki = WikiMemory(root=tmp_path / "mem")
        wiki.init()

        case_with = _make_case_with_memory("w", "q?", _make_memory_setup())
        case_without = EvalCase(id="wo", input={"prompt": "q?"})

        runner = EvalRunner("test", _echo_target, memory=wiki)

        r_with = await runner.run_case(case_with)
        r_without = await runner.run_case(case_without)

        assert r_with.memory_used is True
        assert r_without.memory_used is False


# ---------------------------------------------------------------------------
# CLI --memory flag
# ---------------------------------------------------------------------------


class TestCmdEvalRunMemoryFlag:
    @pytest.mark.asyncio
    async def test_memory_flag_produces_target_suffix(self, tmp_path: Path) -> None:
        """--memory flag appends +memory to the target label."""
        from birkin.eval.cli import cmd_eval_run

        # Write a small dataset
        ds = EvalDataset(
            name="mem-test",
            cases=[_make_case_with_memory("t1", "hello", _make_memory_setup())],
        )
        ds_path = tmp_path / "mem-test.jsonl"
        ds.to_jsonl(ds_path)

        mock_provider = AsyncMock()
        mock_provider.name = "mock"
        mock_provider.model = "test-model"

        mock_response = AsyncMock()
        mock_response.content = "response"
        mock_response.usage = AsyncMock()
        mock_response.usage.prompt_tokens = 5
        mock_response.usage.completion_tokens = 10
        mock_provider.acomplete = AsyncMock(return_value=mock_response)

        with patch("birkin.eval.cli.create_provider", return_value=mock_provider):
            report = await cmd_eval_run(
                dataset_path=str(ds_path),
                provider_name="mock",
                output_dir=str(tmp_path / "out"),
                use_memory=True,
            )

        assert "+memory" in report.target

    @pytest.mark.asyncio
    async def test_no_memory_flag_no_suffix(self, tmp_path: Path) -> None:
        """Without --memory, target label has no +memory suffix."""
        from birkin.eval.cli import cmd_eval_run

        ds = EvalDataset(
            name="no-mem",
            cases=[EvalCase(id="t1", input={"prompt": "hi"})],
        )
        ds_path = tmp_path / "no-mem.jsonl"
        ds.to_jsonl(ds_path)

        mock_provider = AsyncMock()
        mock_provider.name = "mock"
        mock_provider.model = "test-model"

        mock_response = AsyncMock()
        mock_response.content = "response"
        mock_response.usage = AsyncMock()
        mock_response.usage.prompt_tokens = 5
        mock_response.usage.completion_tokens = 10
        mock_provider.acomplete = AsyncMock(return_value=mock_response)

        with patch("birkin.eval.cli.create_provider", return_value=mock_provider):
            report = await cmd_eval_run(
                dataset_path=str(ds_path),
                provider_name="mock",
                output_dir=str(tmp_path / "out"),
                use_memory=False,
            )

        assert "+memory" not in report.target


# ---------------------------------------------------------------------------
# CLI parser integration
# ---------------------------------------------------------------------------


class TestCliParserMemoryFlag:
    def test_eval_run_parser_has_memory_flag(self) -> None:
        """The eval run subparser accepts --memory."""
        from birkin.cli.main import create_parser

        parser = create_parser()
        args = parser.parse_args(["eval", "run", "test.jsonl", "--memory"])
        assert args.memory is True

    def test_eval_run_parser_memory_default_false(self) -> None:
        """--memory defaults to False."""
        from birkin.cli.main import create_parser

        parser = create_parser()
        args = parser.parse_args(["eval", "run", "test.jsonl"])
        assert args.memory is False
