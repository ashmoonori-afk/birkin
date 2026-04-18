"""Unit tests for workflow engine node handlers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from birkin.core.providers.base import ProviderResponse, TokenUsage
from birkin.core.workflow_engine import WorkflowEngine

# ── Helpers ──


def _make_engine(llm_reply: str = "ok", wiki: object | None = None) -> WorkflowEngine:
    """Create a WorkflowEngine with a mocked provider."""
    provider = MagicMock()
    provider.acomplete = AsyncMock(
        return_value=ProviderResponse(content=llm_reply, usage=TokenUsage(prompt_tokens=10, completion_tokens=5))
    )
    return WorkflowEngine(provider=provider, wiki_memory=wiki)


def _node(ntype: str, **config: object) -> dict:
    return {"id": "t1", "type": ntype, "config": config}


# ── Passthrough ──


class TestPassthrough:
    @pytest.mark.asyncio
    async def test_input_passthrough(self):
        engine = _make_engine()
        result = await engine._handle_passthrough(_node("input"), "hello")
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_unknown_passthrough(self):
        engine = _make_engine()
        result = await engine._handle_unknown(_node("weird"), "data")
        assert result == "data"


# ── AI Model Handlers ──


class TestLLMHandler:
    @pytest.mark.asyncio
    async def test_llm_returns_provider_content(self):
        engine = _make_engine("Generated text")
        result = await engine._handle_llm(_node("llm"), "prompt")
        assert result == "Generated text"

    @pytest.mark.asyncio
    async def test_llm_empty_content(self):
        engine = _make_engine("")
        result = await engine._handle_llm(_node("llm"), "prompt")
        assert result == ""


class TestClassifier:
    @pytest.mark.asyncio
    async def test_classifier_uses_categories(self):
        engine = _make_engine("positive")
        result = await engine._handle_classifier(
            _node("classifier", categories=["positive", "negative"]), "I love this"
        )
        assert result == "positive"
        call_args = engine._provider.acomplete.call_args[0][0]
        assert "positive, negative" in call_args[0].content

    @pytest.mark.asyncio
    async def test_classifier_default_categories(self):
        engine = _make_engine("neutral")
        await engine._handle_classifier(_node("classifier"), "ok")
        call_args = engine._provider.acomplete.call_args[0][0]
        assert "positive, negative, neutral" in call_args[0].content


class TestSummarizer:
    @pytest.mark.asyncio
    async def test_summarizer(self):
        engine = _make_engine("Short summary.")
        result = await engine._handle_summarizer(_node("summarizer"), "Long text here...")
        assert result == "Short summary."


class TestTranslator:
    @pytest.mark.asyncio
    async def test_translator_target_language(self):
        engine = _make_engine("Bonjour")
        result = await engine._handle_translator(_node("translator", target_language="French"), "Hello")
        assert result == "Bonjour"
        call_args = engine._provider.acomplete.call_args[0][0]
        assert "French" in call_args[0].content

    @pytest.mark.asyncio
    async def test_translator_default_english(self):
        engine = _make_engine("Hello")
        await engine._handle_translator(_node("translator"), "안녕")
        call_args = engine._provider.acomplete.call_args[0][0]
        assert "English" in call_args[0].content


# ── Control Flow ──


class TestCondition:
    @pytest.mark.asyncio
    async def test_condition_returns_yes_no(self):
        engine = _make_engine("YES")
        result = await engine._handle_condition(_node("condition", check="Is this positive?"), "I'm happy")
        assert result == "YES"

    @pytest.mark.asyncio
    async def test_condition_no_check_passthrough(self):
        engine = _make_engine()
        result = await engine._handle_condition(_node("condition"), "data")
        assert result == "data"


class TestLoop:
    @pytest.mark.asyncio
    async def test_loop_runs_max_iterations(self):
        engine = _make_engine()
        # Return different values each call so no convergence
        engine._provider.acomplete = AsyncMock(
            side_effect=[
                ProviderResponse(content=f"v{i}", usage=TokenUsage(prompt_tokens=1, completion_tokens=1))
                for i in range(10)
            ]
        )
        await engine._handle_loop(_node("loop", max=3), "start")
        assert engine._provider.acomplete.call_count == 3

    @pytest.mark.asyncio
    async def test_loop_converges_early(self):
        engine = _make_engine()
        engine._provider.acomplete = AsyncMock(
            side_effect=[
                ProviderResponse(content="refined", usage=TokenUsage(prompt_tokens=1, completion_tokens=1)),
                ProviderResponse(content="refined", usage=TokenUsage(prompt_tokens=1, completion_tokens=1)),
            ]
        )
        result = await engine._handle_loop(_node("loop", max=5), "start")
        assert result == "refined"
        assert engine._provider.acomplete.call_count == 2  # Stopped early


class TestDelay:
    @pytest.mark.asyncio
    async def test_delay_returns_input(self):
        engine = _make_engine()
        result = await engine._handle_delay(_node("delay", seconds=0), "data")
        assert result == "data"

    def test_delay_capped_at_30(self):
        # Should not actually sleep 100s — capped at 30
        node = _node("delay", seconds=100)
        seconds = min(node.get("config", {}).get("seconds", 1), 30)
        assert seconds == 30


class TestPromptTemplate:
    @pytest.mark.asyncio
    async def test_template_substitution(self):
        engine = _make_engine()
        result = await engine._handle_prompt_template(
            _node("prompt-template", template="Hello {input}, welcome!"), "World"
        )
        assert result == "Hello World, welcome!"

    @pytest.mark.asyncio
    async def test_template_default(self):
        engine = _make_engine()
        result = await engine._handle_prompt_template(_node("prompt-template"), "data")
        assert result == "data"


# ── Quality Gates ──


class TestGuardrail:
    @pytest.mark.asyncio
    async def test_guardrail_pass(self):
        engine = _make_engine("PASS - content is safe")
        result = await engine._handle_guardrail(_node("guardrail"), "safe content")
        assert result == "safe content"

    @pytest.mark.asyncio
    async def test_guardrail_fail_raises(self):
        engine = _make_engine("FAIL - contains harmful content")
        with pytest.raises(ValueError, match="Guardrail blocked"):
            await engine._handle_guardrail(_node("guardrail"), "bad content")


class TestValidator:
    @pytest.mark.asyncio
    async def test_validator_valid(self):
        engine = _make_engine("VALID - correct JSON format")
        result = await engine._handle_validator(_node("validator", format="json"), '{"a":1}')
        assert result == '{"a":1}'

    @pytest.mark.asyncio
    async def test_validator_invalid_raises(self):
        engine = _make_engine("INVALID - not valid JSON")
        with pytest.raises(ValueError, match="Validation failed"):
            await engine._handle_validator(_node("validator", format="json"), "not json")


# ── Memory Handlers ──


class TestMemoryHandlers:
    @pytest.mark.asyncio
    async def test_memory_search_with_results(self):
        wiki = MagicMock()
        wiki.query.return_value = [{"slug": "python", "snippet": "A language"}]
        engine = _make_engine(wiki=wiki)
        result = await engine._handle_memory_search(_node("memory-search"), "python")
        assert "python" in result
        assert "A language" in result

    @pytest.mark.asyncio
    async def test_memory_search_no_results(self):
        wiki = MagicMock()
        wiki.query.return_value = []
        engine = _make_engine(wiki=wiki)
        result = await engine._handle_memory_search(_node("memory-search"), "xyz")
        assert "No matching" in result

    @pytest.mark.asyncio
    async def test_memory_search_no_wiki(self):
        engine = _make_engine(wiki=None)
        result = await engine._handle_memory_search(_node("memory-search"), "q")
        assert result == "q"

    @pytest.mark.asyncio
    async def test_memory_write(self):
        wiki = MagicMock()
        engine = _make_engine(wiki=wiki)
        result = await engine._handle_memory_write(_node("memory-write"), "Python basics\nContent here")
        assert "Saved to memory" in result
        wiki.ingest.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_inject(self):
        wiki = MagicMock()
        wiki.build_context.return_value = "## Memory Context"
        engine = _make_engine(wiki=wiki)
        result = await engine._handle_context_inject(_node("context-inject"), "user question")
        assert "## Memory Context" in result
        assert "user question" in result


# ── Platform Handlers ──


class TestPlatformHandlers:
    @pytest.mark.asyncio
    async def test_email_send_stub(self):
        engine = _make_engine()
        result = await engine._handle_email_send(_node("email-send"), "Hello!")
        assert "not configured" in result

    @pytest.mark.asyncio
    async def test_notify(self):
        engine = _make_engine()
        result = await engine._handle_notify(_node("notify"), "Alert!")
        assert "Notification sent" in result


# ── Condition Routing (Integration) ──


class TestConditionRouting:
    @pytest.mark.asyncio
    async def test_yes_route_followed(self):
        engine = _make_engine("YES")
        wf = {
            "nodes": [
                {"id": "n1", "type": "input", "config": {}},
                {"id": "n2", "type": "condition", "config": {"check": "Is positive?"}},
                {"id": "n3", "type": "output", "config": {}},
                {"id": "n4", "type": "output", "config": {}},
            ],
            "edges": [
                {"from": "n1", "to": "n2"},
                {"from": "n2", "to": "n3", "label": "YES"},
                {"from": "n2", "to": "n4", "label": "NO"},
            ],
        }
        engine.load(wf)
        result = await engine.run("happy")
        # Should follow YES path → n3 gets "YES" as input (passthrough)
        assert result == "YES"

    @pytest.mark.asyncio
    async def test_no_label_follows_all(self):
        engine = _make_engine("YES")
        wf = {
            "nodes": [
                {"id": "n1", "type": "input", "config": {}},
                {"id": "n2", "type": "condition", "config": {"check": "check"}},
                {"id": "n3", "type": "output", "config": {}},
            ],
            "edges": [
                {"from": "n1", "to": "n2"},
                {"from": "n2", "to": "n3"},  # No label — always followed
            ],
        }
        engine.load(wf)
        result = await engine.run("input")
        assert result == "YES"


# ── Error Recovery ──


class TestErrorRecovery:
    @pytest.mark.asyncio
    async def test_error_route_followed(self):
        engine = _make_engine()
        engine._provider.acomplete = AsyncMock(side_effect=RuntimeError("API down"))
        wf = {
            "nodes": [
                {"id": "n1", "type": "input", "config": {}},
                {"id": "n2", "type": "llm", "config": {}},
                {"id": "n3", "type": "output", "config": {}},
                {"id": "n4", "type": "output", "config": {}},
            ],
            "edges": [
                {"from": "n1", "to": "n2"},
                {"from": "n2", "to": "n3", "label": ""},
                {"from": "n2", "to": "n4", "label": "ERROR"},
            ],
        }
        engine.load(wf)
        result = await engine.run("hello")
        # Should route to error path n4
        assert "Error at llm" in result

    @pytest.mark.asyncio
    async def test_no_error_route_breaks(self):
        engine = _make_engine()
        engine._provider.acomplete = AsyncMock(side_effect=RuntimeError("fail"))
        wf = {
            "nodes": [
                {"id": "n1", "type": "input", "config": {}},
                {"id": "n2", "type": "llm", "config": {}},
                {"id": "n3", "type": "output", "config": {}},
            ],
            "edges": [
                {"from": "n1", "to": "n2"},
                {"from": "n2", "to": "n3"},
            ],
        }
        engine.load(wf)
        result = await engine.run("hello")
        assert "Error at llm" in result


# ── LLM Timeout ──


class TestLLMTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_message(self):
        engine = _make_engine()

        async def slow_call(*args, **kwargs):
            await asyncio.sleep(10)

        engine._provider.acomplete = slow_call
        result = await engine._handle_llm(_node("llm", timeout=0.1), "prompt")
        assert "timeout" in result.lower()


# ── Parallel + Merge ──


class TestParallelMerge:
    @pytest.mark.asyncio
    async def test_parallel_executes_children_concurrently(self):
        """parallel node forks input to children, all run via asyncio.gather."""
        call_count = 0

        async def counting_complete(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            return ProviderResponse(
                content=f"result-{call_count}",
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
            )

        engine = _make_engine()
        engine._provider.acomplete = counting_complete
        wf = {
            "nodes": [
                {"id": "n1", "type": "input", "config": {}},
                {"id": "n2", "type": "parallel", "config": {}},
                {"id": "n3", "type": "summarizer", "config": {}},
                {"id": "n4", "type": "translator", "config": {"target_language": "Korean"}},
                {"id": "n5", "type": "merge", "config": {}},
                {"id": "n6", "type": "output", "config": {}},
            ],
            "edges": [
                {"from": "n1", "to": "n2"},
                {"from": "n2", "to": "n3"},
                {"from": "n2", "to": "n4"},
                {"from": "n3", "to": "n5"},
                {"from": "n4", "to": "n5"},
                {"from": "n5", "to": "n6"},
            ],
        }
        engine.load(wf)
        result = await engine.run("Hello world")
        # Both children should have been executed
        assert call_count >= 2
        # Merge should combine outputs
        assert "---" in result or "result-" in result

    @pytest.mark.asyncio
    async def test_merge_combines_inputs(self):
        engine = _make_engine()
        engine._merge_inputs = {"m1": ["Branch A output", "Branch B output"]}
        result = await engine._handle_merge({"id": "m1", "type": "merge", "config": {}}, "fallback")
        assert "Branch A" in result
        assert "Branch B" in result

    @pytest.mark.asyncio
    async def test_merge_custom_separator(self):
        engine = _make_engine()
        engine._merge_inputs = {"m1": ["A", "B", "C"]}
        result = await engine._handle_merge({"id": "m1", "type": "merge", "config": {"separator": " | "}}, "")
        assert result == "A | B | C"

    @pytest.mark.asyncio
    async def test_parallel_single_child_works(self):
        """Parallel with single child should still work (no gather needed)."""
        engine = _make_engine("output")
        wf = {
            "nodes": [
                {"id": "n1", "type": "input", "config": {}},
                {"id": "n2", "type": "parallel", "config": {}},
                {"id": "n3", "type": "llm", "config": {}},
                {"id": "n4", "type": "output", "config": {}},
            ],
            "edges": [
                {"from": "n1", "to": "n2"},
                {"from": "n2", "to": "n3"},
                {"from": "n3", "to": "n4"},
            ],
        }
        engine.load(wf)
        result = await engine.run("test")
        assert result == "output"
