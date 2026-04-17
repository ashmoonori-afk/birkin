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
        self._mode: str = "simple"
        self._node_map: dict[str, dict] = {}
        self._adj: dict[str, list[dict]] = {}
        self._results: dict[str, str] = {}

    def _emit(self, evt: dict) -> None:
        if self._event_cb:
            self._event_cb(evt)

    def load(self, workflow: dict) -> None:
        """Load a workflow definition."""
        self._mode = workflow.get("mode", "simple")
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
        """Execute the workflow with the given user input.

        Supports two modes:
        - 'simple' (default): BFS traversal of node graph
        - 'graph': StateGraph engine with conditionals, parallel, loops
        """
        # Check if this is a graph-mode workflow
        if getattr(self, "_mode", "simple") == "graph":
            return await self._run_graph_mode(user_input)

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
            except (OSError, RuntimeError, ValueError, TimeoutError, ConnectionError) as e:
                self._emit({"wf_step": {"id": nid, "type": node["type"], "status": "error", "error": str(e)}})
                logger.error("Workflow node %s (%s) failed: %s", nid, node["type"], e)
                final_output = f"Error at {node['type']}: {e}"
                break

            for next_id in self._next_nodes(nid):
                self._results[next_id] = output
                if next_id not in visited:
                    queue.append(next_id)

        return final_output

    # ── Dispatch table ────────────────────────────────────────────────────
    _NODE_HANDLERS: dict[str, str] = {
        # I/O
        "input": "_handle_passthrough",
        "output": "_handle_passthrough",
        "webhook-trigger": "_handle_passthrough",
        "merge": "_handle_passthrough",
        "parallel": "_handle_passthrough",
        # AI models
        "llm": "_handle_llm",
        "llm-stream": "_handle_llm",
        "classifier": "_handle_classifier",
        "embedder": "_handle_embedder",
        "summarizer": "_handle_summarizer",
        "translator": "_handle_translator",
        "knowledge-extract": "_handle_knowledge_extract",
        # Tools
        "tool-dispatch": "_handle_tool_dispatch",
        "web-search": "_handle_web_search",
        "code-exec": "_handle_shell",
        "shell": "_handle_shell",
        "api-call": "_handle_api_call",
        "file-read": "_handle_file_read",
        "file-write": "_handle_file_write",
        # Memory
        "memory-search": "_handle_memory_search",
        "memory-write": "_handle_memory_write",
        "context-inject": "_handle_context_inject",
        # Control flow
        "condition": "_handle_condition",
        "loop": "_handle_loop",
        "delay": "_handle_delay",
        "prompt-template": "_handle_prompt_template",
        # Quality gates
        "code-review": "_handle_code_review",
        "human-review": "_handle_human_review",
        "guardrail": "_handle_guardrail",
        "validator": "_handle_validator",
        "test-runner": "_handle_test_runner",
        # Platform
        "hn-fetch": "_handle_hn_fetch",
        "telegram-send": "_handle_telegram_send",
        "email-send": "_handle_email_send",
        "notify": "_handle_notify",
    }

    async def _execute_node(self, node: dict, input_text: str) -> str:
        """Execute a single node and return its output."""
        ntype = node.get("type", "")
        handler_name = self._NODE_HANDLERS.get(ntype, "_handle_unknown")
        handler = getattr(self, handler_name)
        return await handler(node, input_text)

    # ── I/O handlers ──────────────────────────────────────────────────

    async def _handle_passthrough(self, node: dict, input_text: str) -> str:
        return input_text

    async def _handle_unknown(self, node: dict, input_text: str) -> str:
        logger.warning(f"Unknown node type: {node.get('type')}, passing through")
        return input_text

    # ── AI model handlers ─────────────────────────────────────────────

    async def _handle_llm(self, node: dict, input_text: str) -> str:
        return await self._run_llm(input_text, node.get("config", {}))

    async def _handle_classifier(self, node: dict, input_text: str) -> str:
        config = node.get("config", {})
        cats = config.get("categories", [])
        cat_str = ", ".join(cats) if cats else "positive, negative, neutral"
        return await self._run_llm(
            f"Classify into one of [{cat_str}]. Reply with only the category name.\n\nText: {input_text}",
            config,
        )

    async def _handle_embedder(self, node: dict, input_text: str) -> str:
        return await self._run_llm(
            "Represent the semantic meaning of this text as a structured description:\n\n" + input_text,
            node.get("config", {}),
        )

    async def _handle_summarizer(self, node: dict, input_text: str) -> str:
        return await self._run_llm(f"Summarize concisely:\n\n{input_text}", node.get("config", {}))

    async def _handle_translator(self, node: dict, input_text: str) -> str:
        config = node.get("config", {})
        lang = config.get("target_language", "English")
        return await self._run_llm(f"Translate to {lang}:\n\n{input_text}", config)

    async def _handle_knowledge_extract(self, node: dict, input_text: str) -> str:
        return await self._run_llm(
            f"Extract key facts and entities from this text as bullet points:\n\n{input_text}",
            node.get("config", {}),
        )

    # ── Tool handlers ─────────────────────────────────────────────────

    async def _handle_tool_dispatch(self, node: dict, input_text: str) -> str:
        tool_name = node.get("config", {}).get("tool", "")
        return await self._run_tool(tool_name, {"input": input_text})

    async def _handle_web_search(self, node: dict, input_text: str) -> str:
        return await self._run_tool("web_search", {"query": input_text.strip()[:200]})

    async def _handle_shell(self, node: dict, input_text: str) -> str:
        return await self._run_tool("shell", {"command": input_text.strip()})

    async def _handle_api_call(self, node: dict, input_text: str) -> str:
        url = node.get("config", {}).get("url", input_text.strip())
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url)
                return f"HTTP {resp.status_code}\n{resp.text[:5000]}"
        except (httpx.HTTPError, OSError, TimeoutError) as e:
            return f"API call failed: {e}"

    async def _handle_file_read(self, node: dict, input_text: str) -> str:
        path = node.get("config", {}).get("path", input_text.strip())
        return await self._run_tool("file_read", {"path": path})

    async def _handle_file_write(self, node: dict, input_text: str) -> str:
        path = node.get("config", {}).get("path", "output.txt")
        return await self._run_tool("file_write", {"path": path, "content": input_text})

    # ── Memory handlers ───────────────────────────────────────────────

    async def _handle_memory_search(self, node: dict, input_text: str) -> str:
        if self._wiki:
            results = self._wiki.query(input_text.strip()[:100])
            if results:
                return "\n\n".join(f"**{r['slug']}**: {r['snippet']}" for r in results)
            return "(No matching memory pages found)"
        return input_text

    async def _handle_memory_write(self, node: dict, input_text: str) -> str:
        if self._wiki:
            slug = input_text.strip().split("\n")[0][:40].lower().replace(" ", "-")
            slug = "".join(c for c in slug if c.isalnum() or c == "-")[:30] or "note"
            self._wiki.ingest("concepts", slug, input_text)
            return f"Saved to memory: concepts/{slug}"
        return input_text

    async def _handle_context_inject(self, node: dict, input_text: str) -> str:
        if self._wiki:
            ctx = self._wiki.build_context(max_pages=5)
            if ctx:
                return f"{ctx}\n\n---\n\n{input_text}"
        return input_text

    # ── Control flow handlers ─────────────────────────────────────────

    async def _handle_condition(self, node: dict, input_text: str) -> str:
        config = node.get("config", {})
        check = config.get("check", "")
        if not check:
            return input_text
        result = await self._run_llm(
            f"Evaluate: {check}\nInput: {input_text}\nReply YES or NO only.",
            config,
        )
        # Return the evaluation result so edge routing can use it
        return result.strip().upper() if result else input_text

    async def _handle_loop(self, node: dict, input_text: str) -> str:
        config = node.get("config", {})
        max_iter = min(config.get("max", 3), 10)
        result = input_text
        for i in range(max_iter):
            result = await self._run_llm(f"Iteration {i + 1}/{max_iter}. Refine:\n\n{result}", config)
        return result

    async def _handle_delay(self, node: dict, input_text: str) -> str:
        seconds = min(node.get("config", {}).get("seconds", 1), 30)
        await asyncio.sleep(seconds)
        return input_text

    async def _handle_prompt_template(self, node: dict, input_text: str) -> str:
        template = node.get("config", {}).get("template", "{input}")
        return template.replace("{input}", input_text)

    # ── Quality gate handlers ─────────────────────────────────────────

    async def _handle_code_review(self, node: dict, input_text: str) -> str:
        review = await self._run_llm(
            "You are a code reviewer. Review this code for bugs, security issues, and improvements:\n\n" + input_text,
            node.get("config", {}),
        )
        return f"--- Code Review ---\n{review}\n\n--- Original ---\n{input_text}"

    async def _handle_human_review(self, node: dict, input_text: str) -> str:
        review = await self._run_llm(
            "Review this content. Flag any issues, then say APPROVED or NEEDS_CHANGES:\n\n" + input_text,
            node.get("config", {}),
        )
        return f"--- Review ---\n{review}\n\n--- Content ---\n{input_text}"

    async def _handle_guardrail(self, node: dict, input_text: str) -> str:
        config = node.get("config", {})
        check = config.get("check", "input")
        result = await self._run_llm(
            f"Check if this {check} is safe and appropriate. Reply PASS or FAIL with reason.\n\n{input_text}",
            config,
        )
        if "FAIL" in result.upper():
            raise ValueError(f"Guardrail blocked: {result}")
        return input_text

    async def _handle_validator(self, node: dict, input_text: str) -> str:
        config = node.get("config", {})
        fmt = config.get("format", "any")
        validation = await self._run_llm(
            f"Validate this output (expected format: {fmt}). Reply VALID or INVALID with details:\n\n{input_text}",
            config,
        )
        if "INVALID" in validation.upper():
            raise ValueError(f"Validation failed: {validation}")
        return input_text

    async def _handle_test_runner(self, node: dict, input_text: str) -> str:
        test_cmd = node.get("config", {}).get("command", f"echo 'Testing: {input_text[:50]}'")
        return await self._run_tool("shell", {"command": test_cmd})

    # ── Platform handlers ─────────────────────────────────────────────

    async def _handle_hn_fetch(self, node: dict, input_text: str) -> str:
        """Fetch top HackerNews stories and format as numbered list."""
        import httpx

        config = node.get("config", {})
        count = min(config.get("count", 10), 50)

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get("https://hacker-news.firebaseio.com/v0/topstories.json")
                resp.raise_for_status()
                story_ids = resp.json()[:count]

                tasks = [client.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json") for sid in story_ids]
                responses = await asyncio.gather(*tasks, return_exceptions=True)

                lines: list[str] = []
                for i, r in enumerate(responses, 1):
                    if isinstance(r, BaseException):
                        continue
                    story = r.json()
                    title = story.get("title", "Untitled")
                    score = story.get("score", 0)
                    url = story.get("url", f"https://news.ycombinator.com/item?id={story_ids[i - 1]}")
                    lines.append(f"{i}. {title} ({score} pts) - {url}")

                return "\n".join(lines) if lines else "No stories fetched."
        except (httpx.HTTPError, OSError, TimeoutError) as e:
            return f"HN fetch failed: {e}"

    async def _handle_telegram_send(self, node: dict, input_text: str) -> str:
        chat_id = node.get("config", {}).get("chat_id", "")
        if chat_id:
            try:
                from birkin.gateway.deps import get_telegram_adapter

                adapter = get_telegram_adapter()
                await adapter.send_message(chat_id=int(chat_id), text=input_text)
                return f"Sent to Telegram chat {chat_id}"
            except (ConnectionError, TimeoutError, OSError, ValueError) as e:
                return f"Telegram send failed: {e}"
        return input_text

    async def _handle_email_send(self, node: dict, input_text: str) -> str:
        return f"[Email would be sent: {input_text[:100]}...] (email not configured)"

    async def _handle_notify(self, node: dict, input_text: str) -> str:
        logger.info(f"Notification: {input_text[:200]}")
        return f"[Notification sent] {input_text[:100]}"

    async def _run_llm(self, prompt: str, config: dict) -> str:
        """Call the LLM provider."""
        messages = [Message(role="user", content=prompt)]
        try:
            response: ProviderResponse = await self._provider.acomplete(messages)
            return response.content or ""
        except (ConnectionError, TimeoutError, RuntimeError) as exc:
            logger.debug("Primary LLM failed (%s), trying fallback", exc)
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
        except (OSError, RuntimeError, ValueError, TimeoutError) as e:
            return f"Tool '{tool_name}' error: {e}"

    async def _run_graph_mode(self, user_input: str) -> str:
        """Execute workflow using the StateGraph engine.

        Converts the loaded node_map/adj into a StateGraph, compiles,
        and runs with the user input as initial state.
        """
        from birkin.core.graph.engine import END, StateGraph
        from birkin.core.graph.node import FunctionNode, NodeResult
        from birkin.core.graph.state import GraphContext

        self._results = {}
        graph = StateGraph()

        # Create FunctionNode for each workflow node
        for nid, node in self._node_map.items():
            node_type = node.get("type", "llm_call")
            # Use dispatch table (handles hyphenated names like hn-fetch, web-search)
            handler_name = self._NODE_HANDLERS.get(node_type)
            handler = getattr(self, handler_name, None) if handler_name else None

            if handler:
                _h, _n = handler, node

                async def _node_run(ctx: GraphContext, h=_h, n=_n) -> NodeResult:
                    input_text = ctx.get("input", "")
                    result = await h(n, input_text)
                    ctx.set("input", result)
                    return NodeResult()

                graph.add_node(FunctionNode(nid, _node_run))
            else:

                async def _passthrough(ctx: GraphContext) -> NodeResult:
                    return NodeResult()

                graph.add_node(FunctionNode(nid, _passthrough))

        # Add edges
        for src, edges in self._adj.items():
            for edge in edges:
                dst = edge.get("to", "")
                if dst in self._node_map:
                    graph.add_edge(src, dst)

        # Set entry point
        starts = self._find_start_nodes()
        if not starts:
            return "Graph workflow has no entry nodes."
        graph.set_entry(starts[0])

        # Last node → END
        terminals = [nid for nid in self._node_map if nid not in self._adj or not self._adj[nid]]
        for t in terminals:
            graph.add_edge(t, END)

        compiled = graph.compile()
        result = await compiled.ainvoke({"input": user_input})
        return result.get("input", "")
