"""Workflow execution engine — runs user-defined node graphs."""

from __future__ import annotations

import logging
from typing import Any, Optional

from birkin.core.models import Message
from birkin.core.providers.base import Provider, ProviderResponse

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """Executes a workflow graph step-by-step.

    A workflow is a dict with:
      - nodes: list of {id, type, config}
      - edges: list of {from, to, label?}

    The engine walks the graph from 'input' nodes to 'output' nodes,
    executing each node's logic and passing data along edges.
    """

    def __init__(
        self,
        provider: Provider,
        *,
        fallback_provider: Optional[Provider] = None,
        event_callback: Optional[Any] = None,
    ) -> None:
        self._provider = provider
        self._fallback = fallback_provider
        self._event_cb = event_callback
        self._node_map: dict[str, dict] = {}
        self._adj: dict[str, list[dict]] = {}  # node_id -> [{to, label}]
        self._results: dict[str, str] = {}  # node_id -> output text

    def _emit(self, evt: dict) -> None:
        if self._event_cb:
            self._event_cb(evt)

    def load(self, workflow: dict) -> None:
        """Load a workflow definition."""
        self._node_map = {n["id"]: n for n in workflow.get("nodes", [])}
        self._adj = {}
        for edge in workflow.get("edges", []):
            src = edge.get("from", "")
            self._adj.setdefault(src, []).append(edge)

    def _find_start_nodes(self) -> list[str]:
        """Find nodes with no incoming edges (entry points)."""
        has_incoming = set()
        for edges in self._adj.values():
            for e in edges:
                has_incoming.add(e.get("to", ""))
        return [nid for nid in self._node_map if nid not in has_incoming or self._node_map[nid].get("type") == "input"]

    def _next_nodes(self, node_id: str) -> list[str]:
        """Get IDs of nodes connected from this node."""
        return [e["to"] for e in self._adj.get(node_id, []) if e.get("to") in self._node_map]

    async def run(self, user_input: str) -> str:
        """Execute the workflow with the given user input.

        Returns the final output text.
        """
        self._results = {}
        starts = self._find_start_nodes()
        if not starts:
            return "Workflow has no entry nodes."

        # Seed input nodes
        for nid in starts:
            node = self._node_map[nid]
            if node.get("type") == "input":
                self._results[nid] = user_input
            else:
                self._results[nid] = user_input

        # BFS execution
        visited: set[str] = set()
        queue = list(starts)
        final_output = user_input

        while queue:
            nid = queue.pop(0)
            if nid in visited:
                continue
            visited.add(nid)

            node = self._node_map.get(nid)
            if not node:
                continue

            # Gather input from all parent nodes
            node_input = self._results.get(nid, user_input)

            # Execute node
            self._emit({"wf_step": {"id": nid, "type": node["type"], "status": "running"}})

            try:
                output = await self._execute_node(node, node_input)
                self._results[nid] = output
                final_output = output
                self._emit({"wf_step": {"id": nid, "type": node["type"], "status": "done"}})
            except Exception as e:
                self._emit({"wf_step": {"id": nid, "type": node["type"], "status": "error", "error": str(e)}})
                logger.error(f"Workflow node {nid} ({node['type']}) failed: {e}")
                final_output = f"Error at {node['type']}: {e}"
                break

            # Propagate output to next nodes
            for next_id in self._next_nodes(nid):
                self._results[next_id] = output
                if next_id not in visited:
                    queue.append(next_id)

        return final_output

    async def _execute_node(self, node: dict, input_text: str) -> str:
        """Execute a single node and return its output."""
        ntype = node.get("type", "")
        config = node.get("config", {})

        if ntype == "input":
            return input_text

        elif ntype == "output":
            return input_text

        elif ntype in ("llm", "llm-stream"):
            return await self._run_llm(input_text, config)

        elif ntype == "prompt-template":
            template = config.get("template", "{input}")
            return template.replace("{input}", input_text)

        elif ntype == "summarizer":
            return await self._run_llm(f"Summarize concisely:\n\n{input_text}", config)

        elif ntype == "translator":
            lang = config.get("target_language", "English")
            return await self._run_llm(f"Translate to {lang}:\n\n{input_text}", config)

        elif ntype == "classifier":
            cats = config.get("categories", [])
            cat_str = ", ".join(cats) if cats else "positive, negative, neutral"
            return await self._run_llm(
                f"Classify into one of [{cat_str}]. Reply with only the category name.\n\nText: {input_text}",
                config,
            )

        elif ntype == "guardrail":
            check = config.get("check", "input")
            result = await self._run_llm(
                f"Check if this {check} is safe and appropriate. Reply PASS or FAIL with reason.\n\n{input_text}",
                config,
            )
            if "FAIL" in result.upper():
                raise ValueError(f"Guardrail blocked: {result}")
            return input_text

        elif ntype == "condition":
            check = config.get("check", "")
            if check == "has_tool_calls":
                return input_text  # pass-through; condition logic handled by edges
            result = await self._run_llm(
                f"Evaluate: {check}\nInput: {input_text}\nReply YES or NO only.",
                config,
            )
            return input_text

        elif ntype == "merge":
            return input_text  # merge just passes through (all inputs already combined)

        elif ntype == "delay":
            import asyncio

            seconds = config.get("seconds", 1)
            await asyncio.sleep(min(seconds, 30))
            return input_text

        elif ntype in ("code-review", "human-review"):
            review = await self._run_llm(
                f"Review this code/content. Provide feedback:\n\n{input_text}",
                config,
            )
            return f"--- Review ---\n{review}\n\n--- Original ---\n{input_text}"

        elif ntype == "validator":
            validation = await self._run_llm(
                f"Validate this output format. Reply VALID or INVALID with details:\n\n{input_text}",
                config,
            )
            if "INVALID" in validation.upper():
                raise ValueError(f"Validation failed: {validation}")
            return input_text

        elif ntype == "knowledge-extract":
            return await self._run_llm(
                f"Extract key facts and entities from this text as bullet points:\n\n{input_text}",
                config,
            )

        elif ntype in ("memory-search", "memory-write", "context-inject"):
            return input_text  # memory operations are pass-through for now

        elif ntype in ("shell", "code-exec"):
            return input_text  # would need tool dispatch; pass-through

        elif ntype in ("web-search", "api-call", "file-read", "file-write"):
            return input_text  # would need tool dispatch; pass-through

        elif ntype in ("telegram-send", "email-send", "notify"):
            return input_text  # notification nodes are pass-through

        elif ntype == "webhook-trigger":
            return input_text

        elif ntype == "loop":
            max_iter = config.get("max", 3)
            result = input_text
            for i in range(min(max_iter, 10)):
                result = await self._run_llm(
                    f"Iteration {i + 1}/{max_iter}. Refine this:\n\n{result}",
                    config,
                )
            return result

        elif ntype == "parallel":
            return input_text  # parallel would need multi-branch; pass-through

        else:
            logger.warning(f"Unknown node type: {ntype}, passing through")
            return input_text

    async def _run_llm(self, prompt: str, config: dict) -> str:
        """Call the LLM provider."""
        messages = [
            Message(role="user", content=prompt),
        ]

        try:
            response: ProviderResponse = await self._provider.acomplete(messages)
            return response.content or ""
        except Exception:
            if self._fallback:
                response = await self._fallback.acomplete(messages)
                return response.content or ""
            raise
