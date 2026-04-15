"""Workflow execution engine — runs user-defined node graphs."""

from __future__ import annotations

import asyncio
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
        wiki_memory: Optional[Any] = None,
    ) -> None:
        self._provider = provider
        self._fallback = fallback_provider
        self._event_cb = event_callback
        self._wiki = wiki_memory
        self._node_map: dict[str, dict] = {}
        self._adj: dict[str, list[dict]] = {}
        self._results: dict[str, str] = {}

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
        has_incoming = set()
        for edges in self._adj.values():
            for e in edges:
                has_incoming.add(e.get("to", ""))
        return [nid for nid in self._node_map if nid not in has_incoming or self._node_map[nid].get("type") == "input"]

    def _next_nodes(self, node_id: str) -> list[str]:
        return [e["to"] for e in self._adj.get(node_id, []) if e.get("to") in self._node_map]

    async def run(self, user_input: str) -> str:
        """Execute the workflow with the given user input."""
        self._results = {}
        starts = self._find_start_nodes()
        if not starts:
            return "Workflow has no entry nodes."

        for nid in starts:
            self._results[nid] = user_input

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

            node_input = self._results.get(nid, user_input)
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

            for next_id in self._next_nodes(nid):
                self._results[next_id] = output
                if next_id not in visited:
                    queue.append(next_id)

        return final_output

    async def _execute_node(self, node: dict, input_text: str) -> str:
        """Execute a single node and return its output."""
        ntype = node.get("type", "")
        config = node.get("config", {})

        # ── I/O ──
        if ntype in ("input", "output", "webhook-trigger"):
            return input_text

        # ── AI Models ──
        elif ntype in ("llm", "llm-stream"):
            return await self._run_llm(input_text, config)

        elif ntype == "classifier":
            cats = config.get("categories", [])
            cat_str = ", ".join(cats) if cats else "positive, negative, neutral"
            return await self._run_llm(
                f"Classify into one of [{cat_str}]. Reply with only the category name.\n\nText: {input_text}",
                config,
            )

        elif ntype == "embedder":
            # Embeddings require a vector API; use LLM to describe the semantic content instead
            return await self._run_llm(
                "Represent the semantic meaning of this text as a structured description:\n\n" + input_text,
                config,
            )

        elif ntype == "summarizer":
            return await self._run_llm(f"Summarize concisely:\n\n{input_text}", config)

        elif ntype == "translator":
            lang = config.get("target_language", "English")
            return await self._run_llm(f"Translate to {lang}:\n\n{input_text}", config)

        # ── Tools (real execution via builtins) ──
        elif ntype == "tool-dispatch":
            tool_name = config.get("tool", "")
            return await self._run_tool(tool_name, {"input": input_text})

        elif ntype == "web-search":
            return await self._run_tool("web_search", {"query": input_text.strip()[:200]})

        elif ntype in ("code-exec", "shell"):
            return await self._run_tool("shell", {"command": input_text.strip()})

        elif ntype == "api-call":
            url = config.get("url", input_text.strip())
            import httpx

            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(url)
                    return f"HTTP {resp.status_code}\n{resp.text[:5000]}"
            except Exception as e:
                return f"API call failed: {e}"

        elif ntype == "file-read":
            path = config.get("path", input_text.strip())
            return await self._run_tool("file_read", {"path": path})

        elif ntype == "file-write":
            path = config.get("path", "output.txt")
            return await self._run_tool("file_write", {"path": path, "content": input_text})

        # ── Memory (real wiki operations) ──
        elif ntype == "memory-search":
            if self._wiki:
                results = self._wiki.query(input_text.strip()[:100])
                if results:
                    return "\n\n".join(f"**{r['slug']}**: {r['snippet']}" for r in results)
                return "(No matching memory pages found)"
            return input_text

        elif ntype == "memory-write":
            if self._wiki:
                # Extract a slug from the first line or first few words
                slug = input_text.strip().split("\n")[0][:40].lower().replace(" ", "-")
                slug = "".join(c for c in slug if c.isalnum() or c == "-")[:30] or "note"
                self._wiki.ingest("concepts", slug, input_text)
                return f"Saved to memory: concepts/{slug}"
            return input_text

        elif ntype == "context-inject":
            if self._wiki:
                ctx = self._wiki.build_context(max_pages=5)
                if ctx:
                    return f"{ctx}\n\n---\n\n{input_text}"
            return input_text

        elif ntype == "knowledge-extract":
            return await self._run_llm(
                f"Extract key facts and entities from this text as bullet points:\n\n{input_text}",
                config,
            )

        # ── Control Flow ──
        elif ntype == "condition":
            check = config.get("check", "")
            if not check:
                return input_text
            result = await self._run_llm(
                f"Evaluate: {check}\nInput: {input_text}\nReply YES or NO only.",
                config,
            )
            # Store the condition result for edge routing (future: use labels)
            return input_text

        elif ntype == "merge":
            return input_text

        elif ntype == "loop":
            max_iter = min(config.get("max", 3), 10)
            result = input_text
            for i in range(max_iter):
                result = await self._run_llm(f"Iteration {i + 1}/{max_iter}. Refine:\n\n{result}", config)
            return result

        elif ntype == "delay":
            seconds = min(config.get("seconds", 1), 30)
            await asyncio.sleep(seconds)
            return input_text

        elif ntype == "parallel":
            # Execute all next nodes concurrently (simplified: just pass through)
            return input_text

        elif ntype == "prompt-template":
            template = config.get("template", "{input}")
            return template.replace("{input}", input_text)

        # ── Quality Gates ──
        elif ntype == "code-review":
            review = await self._run_llm(
                "You are a code reviewer. Review this code for bugs, security issues, and improvements:\n\n"
                + input_text,
                config,
            )
            return f"--- Code Review ---\n{review}\n\n--- Original ---\n{input_text}"

        elif ntype == "human-review":
            # In a real system this would pause and wait for approval.
            # For now, the LLM acts as reviewer and always passes.
            review = await self._run_llm(
                "Review this content. Flag any issues, then say APPROVED or NEEDS_CHANGES:\n\n" + input_text,
                config,
            )
            return f"--- Review ---\n{review}\n\n--- Content ---\n{input_text}"

        elif ntype == "guardrail":
            check = config.get("check", "input")
            result = await self._run_llm(
                f"Check if this {check} is safe and appropriate. Reply PASS or FAIL with reason.\n\n{input_text}",
                config,
            )
            if "FAIL" in result.upper():
                raise ValueError(f"Guardrail blocked: {result}")
            return input_text

        elif ntype == "validator":
            fmt = config.get("format", "any")
            validation = await self._run_llm(
                f"Validate this output (expected format: {fmt}). Reply VALID or INVALID with details:\n\n{input_text}",
                config,
            )
            if "INVALID" in validation.upper():
                raise ValueError(f"Validation failed: {validation}")
            return input_text

        elif ntype == "test-runner":
            # Run the input as a shell test command
            test_cmd = config.get("command", f"echo 'Testing: {input_text[:50]}'")
            return await self._run_tool("shell", {"command": test_cmd})

        # ── Platform ──
        elif ntype == "telegram-send":
            chat_id = config.get("chat_id", "")
            if chat_id:
                try:
                    from birkin.gateway.deps import get_telegram_adapter

                    adapter = get_telegram_adapter()
                    await adapter.send_message(chat_id=int(chat_id), text=input_text)
                    return f"Sent to Telegram chat {chat_id}"
                except Exception as e:
                    return f"Telegram send failed: {e}"
            return input_text

        elif ntype == "email-send":
            return f"[Email would be sent: {input_text[:100]}...] (email not configured)"

        elif ntype == "notify":
            logger.info(f"Notification: {input_text[:200]}")
            return f"[Notification sent] {input_text[:100]}"

        else:
            logger.warning(f"Unknown node type: {ntype}, passing through")
            return input_text

    async def _run_llm(self, prompt: str, config: dict) -> str:
        """Call the LLM provider."""
        messages = [Message(role="user", content=prompt)]
        try:
            response: ProviderResponse = await self._provider.acomplete(messages)
            return response.content or ""
        except Exception:
            if self._fallback:
                response = await self._fallback.acomplete(messages)
                return response.content or ""
            raise

    async def _run_tool(self, tool_name: str, args: dict) -> str:
        """Execute a built-in tool by name."""
        from birkin.tools.base import ToolContext
        from birkin.tools.registry import get_registry

        registry = get_registry()
        tool = registry.get(tool_name)
        if not tool:
            return f"Tool '{tool_name}' not found"

        try:
            ctx = ToolContext(working_dir=".")
            result = await tool.execute(args=args, context=ctx)
            return result.output if result.success else (result.error or "Tool failed")
        except Exception as e:
            return f"Tool '{tool_name}' error: {e}"
