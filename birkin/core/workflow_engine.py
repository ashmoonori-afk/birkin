"""Workflow execution engine — runs user-defined node graphs."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar, Optional

from birkin.core.models import Message
from birkin.core.providers.base import Provider, ProviderResponse

logger = logging.getLogger(__name__)

_LLM_TIMEOUT_SECONDS = 120  # Default timeout for LLM calls in workflow nodes


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

    def _next_nodes(self, node_id: str, output: str | None = None) -> list[str]:
        """Return next node IDs to visit.

        For condition/switch nodes, only follow edges whose label matches the
        output. For try-catch, route based on _last_try_catch_status.
        If no labelled edges match, follow all edges as fallback.
        """
        edges = self._adj.get(node_id, [])
        node = self._node_map.get(node_id)
        ntype = node.get("type", "") if node else ""
        if ntype in ("condition", "switch") and output:
            normalised = output.strip().upper()
            labelled = [
                e["to"] for e in edges if e.get("label", "").strip().upper() == normalised and e["to"] in self._node_map
            ]
            if labelled:
                return labelled
        if ntype == "try-catch":
            status = getattr(self, "_last_try_catch_status", "success").upper()
            labelled = [
                e["to"] for e in edges if e.get("label", "").strip().upper() == status and e["to"] in self._node_map
            ]
            if labelled:
                return labelled
        return [e["to"] for e in edges if e.get("to") in self._node_map]

    async def run(self, user_input: str) -> str:  # noqa: C901
        """Execute the workflow with the given user input.

        Supports two modes:
        - 'simple' (default): BFS traversal of node graph
        - 'graph': StateGraph engine with conditionals, parallel, loops
        """
        # Check if this is a graph-mode workflow
        if getattr(self, "_mode", "simple") == "graph":
            return await self._run_graph_mode(user_input)

        self._results = {}
        self._merge_inputs: dict[str, list[str]] = {}
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
                error_msg = f"Error at {node['type']}: {e}"

                # Check for error-recovery edges (label="ERROR")
                error_edges = self._next_nodes(nid, "ERROR")
                normal_edges = [e_to for e_to in self._next_nodes(nid) if e_to not in error_edges]
                if error_edges and error_edges != normal_edges:
                    # Route to error-handling path instead of stopping
                    for next_id in error_edges:
                        self._results[next_id] = error_msg
                        if next_id not in visited:
                            queue.append(next_id)
                    final_output = error_msg
                    continue

                # No error path — stop workflow
                final_output = error_msg
                break

            next_ids = self._next_nodes(nid, output)

            # Parallel node: execute all children concurrently
            if node.get("type") == "parallel" and len(next_ids) > 1:
                child_tasks = []
                for cid in next_ids:
                    child_node = self._node_map.get(cid)
                    if child_node:
                        child_tasks.append(self._execute_node(child_node, output))
                if child_tasks:
                    self._emit({"wf_step": {"id": nid, "type": "parallel", "status": "forking", "children": next_ids}})
                    results = await asyncio.gather(*child_tasks, return_exceptions=True)
                    for i, cid in enumerate(next_ids):
                        r = results[i]
                        child_output = str(r) if isinstance(r, BaseException) else r
                        self._results[cid] = child_output
                        visited.add(cid)
                        self._emit({"wf_step": {"id": cid, "type": self._node_map[cid]["type"], "status": "done"}})
                        # Collect outputs for downstream merge nodes
                        for grandchild in self._next_nodes(cid, child_output):
                            if self._node_map.get(grandchild, {}).get("type") == "merge":
                                self._merge_inputs.setdefault(grandchild, []).append(child_output)
                            self._results[grandchild] = child_output
                            if grandchild not in visited:
                                queue.append(grandchild)
                    continue

            for next_id in next_ids:
                self._results[next_id] = output
                if next_id not in visited:
                    queue.append(next_id)

        # Workflow → Memory: capture results as wiki page
        if self._wiki and final_output and final_output != user_input:
            try:
                from datetime import datetime

                slug = f"wf-{starts[0]}-{datetime.now():%Y%m%d-%H%M}"
                self._wiki.ingest("workflows", slug, final_output, tags=["workflow-result"])
            except Exception:
                logger.debug("Failed to save workflow result to wiki", exc_info=True)

        return final_output

    # ── Dispatch table ────────────────────────────────────────────────────
    _NODE_HANDLERS: ClassVar[dict[str, str]] = {
        # I/O
        "input": "_handle_passthrough",
        "output": "_handle_passthrough",
        "webhook-trigger": "_handle_passthrough",
        "merge": "_handle_merge",
        "parallel": "_handle_parallel",
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
        # ── Extended control flow ──────────────────────────────────────
        "switch": "_handle_switch",
        "for-each": "_handle_for_each",
        "try-catch": "_handle_try_catch",
        "cron-trigger": "_handle_passthrough",
        # ── Data transformation ────────────────────────────────────────
        "csv-parse": "_handle_csv_parse",
        "json-transform": "_handle_json_transform",
        "pdf-extract": "_handle_pdf_extract",
        "data-format": "_handle_data_format",
        # ── Scheduling ─────────────────────────────────────────────────
        "datetime": "_handle_datetime",
        "rate-limit": "_handle_rate_limit",
        # ── Communication ──────────────────────────────────────────────
        "slack-send": "_handle_slack_send",
        "discord-send": "_handle_discord_send",
        "sms-send": "_handle_sms_send",
        "webhook-send": "_handle_webhook_send",
        "email-read": "_handle_email_read",
        # ── Image & Media ──────────────────────────────────────────────
        "image-resize": "_handle_image_resize",
        "image-generate": "_handle_image_generate",
        "vision-analyze": "_handle_vision_analyze",
        "audio-transcribe": "_handle_audio_transcribe",
        # ── Database ───────────────────────────────────────────────────
        "db-query": "_handle_db_query",
        "db-write": "_handle_db_write",
        "cloud-storage": "_handle_cloud_storage",
        # ── Web & RSS ──────────────────────────────────────────────────
        "rss-fetch": "_handle_rss_fetch",
        "web-scrape": "_handle_web_scrape",
        "html-parse": "_handle_html_parse",
        # ── Calendar & Tasks ───────────────────────────────────────────
        "calendar-event": "_handle_calendar_event",
        "task-create": "_handle_task_create",
        # ── Document Generation ────────────────────────────────────────
        "pdf-generate": "_handle_pdf_generate",
        "spreadsheet-write": "_handle_spreadsheet_write",
        # ── Security ───────────────────────────────────────────────────
        "secret-inject": "_handle_secret_inject",
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
        logger.warning("Unknown node type: %s, passing through", node.get("type"))
        return input_text

    # ── AI model handlers ─────────────────────────────────────────────

    async def _handle_llm(self, node: dict, input_text: str) -> str:
        config = node.get("config", {})
        # Memory → Workflow: inject relevant memory context
        if self._wiki and config.get("inject_memory", True):
            try:
                ctx = self._wiki.build_context(max_pages=3)
                if ctx:
                    input_text = f"[Memory Context]\n{ctx}\n\n[User Request]\n{input_text}"
            except Exception:
                pass  # never break workflow for memory failure
        return await self._run_llm(input_text, config)

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
        prev_result = None
        for i in range(max_iter):
            result = await self._run_llm(f"Iteration {i + 1}/{max_iter}. Refine:\n\n{result}", config)
            # Early exit if output converged (same result twice in a row)
            if result == prev_result:
                logger.info("Loop converged at iteration %d/%d", i + 1, max_iter)
                break
            prev_result = result
        return result

    async def _handle_delay(self, node: dict, input_text: str) -> str:
        seconds = min(node.get("config", {}).get("seconds", 1), 30)
        await asyncio.sleep(seconds)
        return input_text

    async def _handle_prompt_template(self, node: dict, input_text: str) -> str:
        template = node.get("config", {}).get("template", "{input}")
        return template.replace("{input}", input_text)

    async def _handle_parallel(self, node: dict, input_text: str) -> str:
        """Fork input to all child nodes and execute concurrently.

        Returns input unchanged — actual parallel work happens in run()
        which detects parallel nodes and uses asyncio.gather on children.
        The output is passed to all outgoing edges as-is.
        """
        return input_text

    async def _handle_merge(self, node: dict, input_text: str) -> str:
        """Merge multiple inputs from parallel branches.

        Collects all inputs stored in _merge_inputs[node_id] by the
        run() loop and joins them with separators.
        """
        inputs = self._merge_inputs.get(node["id"], [input_text])
        separator = node.get("config", {}).get("separator", "\n\n---\n\n")
        return separator.join(inputs)

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
        logger.info("Notification: %s", input_text[:200])
        return f"[Notification sent] {input_text[:100]}"

    # ── Control Flow (extended) ──────────────────────────────────────

    async def _handle_switch(self, node: dict, input_text: str) -> str:
        """Multi-way branch via LLM classification against config.cases."""
        try:
            config = node.get("config", {})
            cases = config.get("cases", {})
            case_labels = ", ".join(cases.keys()) if cases else "A, B, C"
            result = await self._run_llm(
                f"Classify into one of [{case_labels}]. Reply with only the label.\n\nText: {input_text}",
                config,
            )
            return result.strip()
        except Exception as e:
            return f"[switch error] {e}"

    async def _handle_for_each(self, node: dict, input_text: str) -> str:
        """Iterate over items (JSON array or lines)."""
        try:
            import json as _json

            config = node.get("config", {})
            max_items = min(config.get("max_items", 20), 100)
            try:
                items = _json.loads(input_text)
                if not isinstance(items, list):
                    items = [str(items)]
            except (ValueError, TypeError):
                items = input_text.strip().splitlines()
            items = items[:max_items]
            children = config.get("children", [])
            results: list[str] = []
            for item in items:
                item_str = item if isinstance(item, str) else _json.dumps(item)
                if children:
                    out = await self._execute_subgraph(children, item_str)
                else:
                    out = item_str
                results.append(out)
            return "\n".join(results)
        except Exception as e:
            return f"[for-each error] {e}"

    async def _handle_try_catch(self, node: dict, input_text: str) -> str:
        """Execute subgraph; capture errors instead of raising."""
        try:
            config = node.get("config", {})
            children = config.get("children", [])
            result = await self._execute_subgraph(children, input_text)
            self._last_try_catch_status = "success"
            return result
        except Exception as e:
            self._last_try_catch_status = "error"
            return f"[try-catch error] {e}"

    # ── Data Transformation ────────────────────────────────────────────

    async def _handle_csv_parse(self, node: dict, input_text: str) -> str:
        """Parse CSV input into JSON, markdown, or summary."""
        try:
            import csv
            import io
            import json as _json

            config = node.get("config", {})
            fmt = config.get("format", "json")
            reader = csv.DictReader(io.StringIO(input_text))
            rows = list(reader)
            if fmt == "markdown":
                if not rows:
                    return "(empty CSV)"
                headers = list(rows[0].keys())
                lines = ["| " + " | ".join(headers) + " |"]
                lines.append("| " + " | ".join("---" for _ in headers) + " |")
                for r in rows:
                    lines.append("| " + " | ".join(str(r.get(h, "")) for h in headers) + " |")
                return "\n".join(lines)
            if fmt == "summary":
                return f"CSV: {len(rows)} rows, columns: {list(rows[0].keys()) if rows else []}"
            return _json.dumps(rows, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"[csv-parse error] {e}"

    async def _handle_json_transform(self, node: dict, input_text: str) -> str:
        """Extract a dot-path expression from JSON input."""
        try:
            import json as _json

            config = node.get("config", {})
            expression = config.get("expression", "")
            fmt = config.get("format", "json")
            data = _json.loads(input_text)
            if expression:
                for key in expression.split("."):
                    if isinstance(data, dict):
                        data = data.get(key)
                    elif isinstance(data, list) and key.isdigit():
                        data = data[int(key)]
                    else:
                        data = None
                        break
            if fmt == "lines" and isinstance(data, list):
                return "\n".join(str(item) for item in data)
            return _json.dumps(data, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"[json-transform error] {e}"

    async def _handle_pdf_extract(self, node: dict, input_text: str) -> str:
        """Extract text from a PDF file using pymupdf."""
        try:
            try:
                import fitz
            except ImportError:
                return "[pdf-extract] pymupdf not installed. Run: pip install pymupdf"
            config = node.get("config", {})
            path = config.get("path", input_text.strip())
            doc = fitz.open(path)
            pages: list[str] = []
            max_pages = min(config.get("max_pages", 50), 200)
            for i, page in enumerate(doc):
                if i >= max_pages:
                    break
                pages.append(page.get_text())
            doc.close()
            return "\n\n".join(pages) if pages else "(empty PDF)"
        except Exception as e:
            return f"[pdf-extract error] {e}"

    async def _handle_data_format(self, node: dict, input_text: str) -> str:
        """Auto-detect JSON/CSV input and convert to target format."""
        try:
            import csv
            import io
            import json as _json

            config = node.get("config", {})
            to_fmt = config.get("to", "json")
            # Try JSON first
            try:
                data = _json.loads(input_text)
                rows = data if isinstance(data, list) else [data]
            except (ValueError, TypeError):
                reader = csv.DictReader(io.StringIO(input_text))
                rows = list(reader)
            if to_fmt == "csv":
                if not rows:
                    return ""
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
                return output.getvalue()
            if to_fmt == "markdown":
                if not rows:
                    return "(empty)"
                headers = list(rows[0].keys())
                lines = ["| " + " | ".join(headers) + " |"]
                lines.append("| " + " | ".join("---" for _ in headers) + " |")
                for r in rows:
                    lines.append("| " + " | ".join(str(r.get(h, "")) for h in headers) + " |")
                return "\n".join(lines)
            return _json.dumps(rows, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"[data-format error] {e}"

    # ── Scheduling ─────────────────────────────────────────────────────

    async def _handle_datetime(self, node: dict, input_text: str) -> str:
        """Datetime operations: now, format, add, parse."""
        try:
            from datetime import datetime, timedelta

            config = node.get("config", {})
            op = config.get("operation", "now")
            if op == "now":
                fmt = config.get("format", "%Y-%m-%d %H:%M:%S")
                return datetime.now().strftime(fmt)
            if op == "format":
                fmt = config.get("format", "%Y-%m-%d")
                dt = datetime.fromisoformat(input_text.strip())
                return dt.strftime(fmt)
            if op == "add":
                days = config.get("days", 0)
                hours = config.get("hours", 0)
                dt = datetime.fromisoformat(input_text.strip())
                dt += timedelta(days=days, hours=hours)
                return dt.isoformat()
            if op == "parse":
                dt = datetime.fromisoformat(input_text.strip())
                return dt.isoformat()
            return input_text
        except Exception as e:
            return f"[datetime error] {e}"

    async def _handle_rate_limit(self, node: dict, input_text: str) -> str:
        """Rate-limit node execution by calls_per_minute."""
        try:
            import time

            config = node.get("config", {})
            cpm = config.get("calls_per_minute", 60)
            node_id = node.get("id", "unknown")
            if not hasattr(self, "_rate_limit_log"):
                self._rate_limit_log: dict[str, list[float]] = {}
            now = time.time()
            log = self._rate_limit_log.setdefault(node_id, [])
            # Purge entries older than 60s
            log[:] = [t for t in log if now - t < 60]
            if len(log) >= cpm:
                wait = 60 - (now - log[0])
                if wait > 0:
                    await asyncio.sleep(min(wait, 30))
            log.append(time.time())
            return input_text
        except Exception as e:
            return f"[rate-limit error] {e}"

    # ── Communication ──────────────────────────────────────────────────

    async def _handle_slack_send(self, node: dict, input_text: str) -> str:
        """Send message to Slack via incoming webhook."""
        try:
            import os

            import httpx

            config = node.get("config", {})
            url = config.get("webhook_url") or os.environ.get("SLACK_WEBHOOK_URL", "")
            if not url:
                return "[slack] No webhook URL configured"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json={"text": input_text[:4000]})
                return f"Slack: HTTP {resp.status_code}"
        except Exception as e:
            return f"[slack error] {e}"

    async def _handle_discord_send(self, node: dict, input_text: str) -> str:
        """Send message to Discord via webhook."""
        try:
            import os

            import httpx

            config = node.get("config", {})
            url = config.get("webhook_url") or os.environ.get("DISCORD_WEBHOOK_URL", "")
            if not url:
                return "[discord] No webhook URL configured"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json={"content": input_text[:2000]})
                return f"Discord: HTTP {resp.status_code}"
        except Exception as e:
            return f"[discord error] {e}"

    async def _handle_sms_send(self, node: dict, input_text: str) -> str:
        """Send SMS via Twilio API."""
        try:
            import os

            import httpx

            config = node.get("config", {})
            account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
            auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
            from_number = os.environ.get("TWILIO_FROM_NUMBER", "")
            to_number = config.get("to", "")
            if not all([account_sid, auth_token, from_number, to_number]):
                return "[sms] Missing Twilio configuration"
            url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    url,
                    auth=(account_sid, auth_token),
                    data={"From": from_number, "To": to_number, "Body": input_text[:1600]},
                )
                return f"SMS: HTTP {resp.status_code}"
        except Exception as e:
            return f"[sms error] {e}"

    async def _handle_webhook_send(self, node: dict, input_text: str) -> str:
        """Send HTTP request to a configured webhook URL."""
        try:
            import httpx

            config = node.get("config", {})
            url = config.get("url", "")
            if not url:
                return "[webhook] No URL configured"
            method = config.get("method", "POST").upper()
            headers = config.get("headers", {})
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.request(method, url, headers=headers, content=input_text)
                return f"Webhook: HTTP {resp.status_code}\n{resp.text[:2000]}"
        except Exception as e:
            return f"[webhook error] {e}"

    async def _handle_email_read(self, node: dict, input_text: str) -> str:
        """Read emails via IMAP."""
        try:
            import email
            import imaplib
            import os

            config = node.get("config", {})
            host = config.get("host") or os.environ.get("IMAP_HOST", "")
            user = config.get("user") or os.environ.get("IMAP_USER", "")
            password = config.get("password") or os.environ.get("IMAP_PASSWORD", "")
            folder = config.get("folder", "INBOX")
            count = min(config.get("count", 5), 20)
            if not all([host, user, password]):
                return "[email-read] Missing IMAP configuration"
            loop = asyncio.get_event_loop()

            def _fetch():
                mail = imaplib.IMAP4_SSL(host)
                mail.login(user, password)
                mail.select(folder)
                _, data = mail.search(None, "ALL")
                ids = data[0].split()[-count:]
                results = []
                for mid in ids:
                    _, msg_data = mail.fetch(mid, "(RFC822)")
                    msg = email.message_from_bytes(msg_data[0][1])
                    subj = msg.get("Subject", "(no subject)")
                    frm = msg.get("From", "")
                    results.append(f"From: {frm}\nSubject: {subj}")
                mail.logout()
                return "\n---\n".join(results)

            return await loop.run_in_executor(None, _fetch)
        except Exception as e:
            return f"[email-read error] {e}"

    # ── Image & Media ──────────────────────────────────────────────────

    async def _handle_image_resize(self, node: dict, input_text: str) -> str:
        """Resize an image using Pillow."""
        try:
            try:
                from PIL import Image
            except ImportError:
                return "[image-resize] Pillow not installed. Run: pip install Pillow"
            config = node.get("config", {})
            path = config.get("path", input_text.strip())
            width = config.get("width", 800)
            height = config.get("height", 600)
            output = config.get("output", path)
            img = Image.open(path)
            img = img.resize((width, height))
            img.save(output)
            return f"Resized to {width}x{height}: {output}"
        except Exception as e:
            return f"[image-resize error] {e}"

    async def _handle_image_generate(self, node: dict, input_text: str) -> str:
        """Generate an image via OpenAI DALL-E API."""
        try:
            import os

            import httpx

            config = node.get("config", {})
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                return "[image-generate] OPENAI_API_KEY not set"
            prompt = config.get("prompt", input_text[:1000])
            size = config.get("size", "1024x1024")
            output_path = config.get("output", "generated_image.png")
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"prompt": prompt, "n": 1, "size": size, "response_format": "url"},
                )
                resp.raise_for_status()
                url = resp.json()["data"][0]["url"]
                img_resp = await client.get(url)
                with open(output_path, "wb") as f:
                    f.write(img_resp.content)
            return f"Image saved: {output_path}"
        except Exception as e:
            return f"[image-generate error] {e}"

    async def _handle_vision_analyze(self, node: dict, input_text: str) -> str:
        """Analyze an image via OpenAI Vision API."""
        try:
            import base64
            import os

            import httpx

            config = node.get("config", {})
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                return "[vision] OPENAI_API_KEY not set"
            path = config.get("path", input_text.strip())
            prompt = config.get("prompt", "Describe this image in detail.")
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": config.get("model", "gpt-4o"),
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                                ],
                            }
                        ],
                        "max_tokens": 1000,
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[vision error] {e}"

    async def _handle_audio_transcribe(self, node: dict, input_text: str) -> str:
        """Transcribe audio via OpenAI Whisper API."""
        try:
            import os

            import httpx

            config = node.get("config", {})
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                return "[audio-transcribe] OPENAI_API_KEY not set"
            path = config.get("path", input_text.strip())
            async with httpx.AsyncClient(timeout=120) as client:
                with open(path, "rb") as f:
                    resp = await client.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        files={"file": (os.path.basename(path), f, "audio/mpeg")},
                        data={"model": "whisper-1"},
                    )
                resp.raise_for_status()
                return resp.json().get("text", "")
        except Exception as e:
            return f"[audio-transcribe error] {e}"

    # ── Database ───────────────────────────────────────────────────────

    async def _handle_db_query(self, node: dict, input_text: str) -> str:
        """Execute a SELECT-only SQLite query."""
        try:
            import json as _json
            import sqlite3

            config = node.get("config", {})
            db_path = config.get("db", ":memory:")
            query = config.get("query", input_text.strip())
            # Block dangerous statements
            upper_q = query.upper().strip()
            if any(kw in upper_q for kw in ["DROP", "DELETE", "ALTER", "INSERT", "UPDATE"]):
                return "[db-query] Only SELECT queries allowed"
            loop = asyncio.get_event_loop()

            def _run():
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cur = conn.execute(query)
                rows = [dict(r) for r in cur.fetchall()]
                conn.close()
                return _json.dumps(rows, ensure_ascii=False, default=str)

            return await loop.run_in_executor(None, _run)
        except Exception as e:
            return f"[db-query error] {e}"

    async def _handle_db_write(self, node: dict, input_text: str) -> str:
        """Execute INSERT/UPDATE SQLite statements."""
        try:
            import sqlite3

            config = node.get("config", {})
            db_path = config.get("db", ":memory:")
            query = config.get("query", input_text.strip())
            upper_q = query.upper().strip()
            if any(kw in upper_q for kw in ["DROP", "SELECT", "ALTER"]):
                return "[db-write] Only INSERT/UPDATE queries allowed"
            loop = asyncio.get_event_loop()

            def _run():
                conn = sqlite3.connect(db_path)
                conn.execute(query)
                conn.commit()
                changes = conn.total_changes
                conn.close()
                return f"DB write OK. Rows affected: {changes}"

            return await loop.run_in_executor(None, _run)
        except Exception as e:
            return f"[db-write error] {e}"

    async def _handle_cloud_storage(self, node: dict, input_text: str) -> str:
        """AWS S3 operations via CLI subprocess."""
        try:
            import subprocess

            config = node.get("config", {})
            operation = config.get("operation", "list")
            bucket = config.get("bucket", "")
            path = config.get("path", input_text.strip())
            if operation == "upload":
                cmd = ["aws", "s3", "cp", path, f"s3://{bucket}/"]
            elif operation == "download":
                local = config.get("local_path", "./download")
                cmd = ["aws", "s3", "cp", f"s3://{bucket}/{path}", local]
            else:
                cmd = ["aws", "s3", "ls", f"s3://{bucket}/{path}" if bucket else ""]
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            )
            return result.stdout or result.stderr or "(no output)"
        except Exception as e:
            return f"[cloud-storage error] {e}"

    # ── Web & RSS ──────────────────────────────────────────────────────

    async def _handle_rss_fetch(self, node: dict, input_text: str) -> str:
        """Fetch and parse RSS/Atom feed."""
        try:
            import xml.etree.ElementTree as ET

            import httpx

            config = node.get("config", {})
            url = config.get("url", input_text.strip())
            count = min(config.get("count", 10), 50)
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url)
                resp.raise_for_status()
            root = ET.fromstring(resp.text)
            items: list[str] = []
            # RSS 2.0
            for item in root.iter("item"):
                title = item.findtext("title", "")
                link = item.findtext("link", "")
                items.append(f"- {title} ({link})")
                if len(items) >= count:
                    break
            # Atom fallback
            if not items:
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                for entry in root.findall(".//atom:entry", ns):
                    title = entry.findtext("atom:title", "", ns)
                    link_el = entry.find("atom:link", ns)
                    link = link_el.get("href", "") if link_el is not None else ""
                    items.append(f"- {title} ({link})")
                    if len(items) >= count:
                        break
            return "\n".join(items) if items else "(no items found)"
        except Exception as e:
            return f"[rss-fetch error] {e}"

    async def _handle_web_scrape(self, node: dict, input_text: str) -> str:
        """Scrape text content from a URL using regex extraction."""
        try:
            import re

            import httpx

            config = node.get("config", {})
            url = config.get("url", input_text.strip())
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
            html = resp.text
            # Remove script/style
            html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
            # Remove tags
            text = re.sub(r"<[^>]+>", " ", html)
            # Collapse whitespace
            text = re.sub(r"\s+", " ", text).strip()
            max_len = config.get("max_length", 5000)
            return text[:max_len]
        except Exception as e:
            return f"[web-scrape error] {e}"

    async def _handle_html_parse(self, node: dict, input_text: str) -> str:
        """Extract tags/attributes from HTML input via regex."""
        try:
            import re

            config = node.get("config", {})
            tag = config.get("tag", "a")
            attr = config.get("attribute", "href")
            pattern = rf'<{tag}[^>]*{attr}=["\']([^"\']*)["\'][^>]*>'
            matches = re.findall(pattern, input_text, re.IGNORECASE)
            return "\n".join(matches) if matches else f"(no <{tag} {attr}=> found)"
        except Exception as e:
            return f"[html-parse error] {e}"

    # ── Calendar & Tasks ───────────────────────────────────────────────

    async def _handle_calendar_event(self, node: dict, input_text: str) -> str:
        """Generate an iCal VCALENDAR event."""
        try:
            from datetime import datetime

            config = node.get("config", {})
            summary = config.get("summary", input_text[:100])
            dtstart = config.get("dtstart", datetime.now().strftime("%Y%m%dT%H%M%S"))
            dtend = config.get("dtend", "")
            location = config.get("location", "")
            lines = [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "BEGIN:VEVENT",
                f"SUMMARY:{summary}",
                f"DTSTART:{dtstart}",
            ]
            if dtend:
                lines.append(f"DTEND:{dtend}")
            if location:
                lines.append(f"LOCATION:{location}")
            lines.append(f"DESCRIPTION:{input_text[:500]}")
            lines.extend(["END:VEVENT", "END:VCALENDAR"])
            return "\n".join(lines)
        except Exception as e:
            return f"[calendar-event error] {e}"

    async def _handle_task_create(self, node: dict, input_text: str) -> str:
        """Create a task via Todoist or Linear API."""
        try:
            import os

            import httpx

            config = node.get("config", {})
            provider = config.get("provider", "todoist")
            title = config.get("title", input_text[:200])
            if provider == "todoist":
                token = os.environ.get("TODOIST_API_TOKEN", "")
                if not token:
                    return "[task-create] TODOIST_API_TOKEN not set"
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(
                        "https://api.todoist.com/rest/v2/tasks",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"content": title, "description": input_text[:1000]},
                    )
                    return f"Todoist: HTTP {resp.status_code}"
            elif provider == "linear":
                token = os.environ.get("LINEAR_API_KEY", "")
                team_id = config.get("team_id", "")
                if not token:
                    return "[task-create] LINEAR_API_KEY not set"
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(
                        "https://api.linear.app/graphql",
                        headers={"Authorization": token},
                        json={
                            "query": "mutation($input:IssueCreateInput!){issueCreate(input:$input){success}}",
                            "variables": {"input": {"title": title, "teamId": team_id}},
                        },
                    )
                    return f"Linear: HTTP {resp.status_code}"
            return f"[task-create] Unknown provider: {provider}"
        except Exception as e:
            return f"[task-create error] {e}"

    # ── Document Generation ────────────────────────────────────────────

    async def _handle_pdf_generate(self, node: dict, input_text: str) -> str:
        """Generate a PDF from text using reportlab."""
        try:
            try:
                from reportlab.lib.pagesizes import letter
                from reportlab.pdfgen import canvas
            except ImportError:
                return "[pdf-generate] reportlab not installed. Run: pip install reportlab"
            config = node.get("config", {})
            output_path = config.get("output", "output.pdf")
            c = canvas.Canvas(output_path, pagesize=letter)
            _width, height = letter
            y = height - 50
            for line in input_text.split("\n"):
                if y < 50:
                    c.showPage()
                    y = height - 50
                c.drawString(50, y, line[:100])
                y -= 14
            c.save()
            return f"PDF generated: {output_path}"
        except Exception as e:
            return f"[pdf-generate error] {e}"

    async def _handle_spreadsheet_write(self, node: dict, input_text: str) -> str:
        """Write JSON/CSV data to an xlsx file using openpyxl."""
        try:
            try:
                from openpyxl import Workbook
            except ImportError:
                return "[spreadsheet-write] openpyxl not installed. Run: pip install openpyxl"
            import csv
            import io
            import json as _json

            config = node.get("config", {})
            output_path = config.get("output", "output.xlsx")
            # Parse input
            try:
                rows = _json.loads(input_text)
                if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                    headers = list(rows[0].keys())
                    data = [[r.get(h, "") for h in headers] for r in rows]
                else:
                    headers = []
                    data = [[str(item)] for item in rows] if isinstance(rows, list) else [[str(rows)]]
            except (ValueError, TypeError):
                reader = csv.reader(io.StringIO(input_text))
                all_rows = list(reader)
                headers = all_rows[0] if all_rows else []
                data = all_rows[1:] if len(all_rows) > 1 else []
            wb = Workbook()
            ws = wb.active
            if headers:
                ws.append(headers)
            for row in data:
                ws.append(row)
            wb.save(output_path)
            return f"Spreadsheet saved: {output_path} ({len(data)} rows)"
        except Exception as e:
            return f"[spreadsheet-write error] {e}"

    # ── Security ───────────────────────────────────────────────────────

    async def _handle_secret_inject(self, node: dict, input_text: str) -> str:
        """Replace {{PLACEHOLDER}} with environment variable values."""
        try:
            import os
            import re

            config = node.get("config", {})
            secrets = config.get("secrets", {})
            result = input_text
            for placeholder, env_var in secrets.items():
                value = os.environ.get(env_var, "")
                result = result.replace(f"{{{{{placeholder}}}}}", value)

            # Also replace any remaining {{VAR}} patterns from env
            def _replace(match):
                key = match.group(1)
                return os.environ.get(key, match.group(0))

            result = re.sub(r"\{\{(\w+)\}\}", _replace, result)
            return result
        except Exception as e:
            return f"[secret-inject error] {e}"

    # ── LLM & Tool helpers ─────────────────────────────────────────────

    async def _run_llm(self, prompt: str, config: dict) -> str:
        """Call the LLM provider. Supports per-node provider override via config."""
        messages = [Message(role="user", content=prompt)]
        timeout = config.get("timeout", _LLM_TIMEOUT_SECONDS)

        # Per-node provider override
        provider = self._provider
        provider_name = config.get("provider", "")
        if provider_name:
            try:
                from birkin.core.providers import create_provider

                provider = create_provider(f"{provider_name}/default")
            except (ValueError, TypeError, ImportError, OSError):
                logger.debug("Node provider '%s' unavailable, using default", provider_name)

        try:
            response: ProviderResponse = await asyncio.wait_for(provider.acomplete(messages), timeout=timeout)
            return response.content or ""
        except TimeoutError:
            logger.warning("LLM call timed out after %ds", timeout)
            if self._fallback:
                response = await asyncio.wait_for(self._fallback.acomplete(messages), timeout=timeout)
                return response.content or ""
            return f"[LLM timeout after {timeout}s]"
        except (ConnectionError, RuntimeError) as exc:
            logger.debug("Primary LLM failed (%s), trying fallback", exc)
            if self._fallback:
                response = await self._fallback.acomplete(messages)
                return response.content or ""
            raise

    async def _execute_subgraph(self, child_ids: list[str], input_text: str) -> str:
        """Run a sub-sequence of nodes and return the last output."""
        result = input_text
        for cid in child_ids:
            child_node = self._node_map.get(cid)
            if child_node:
                result = await self._execute_node(child_node, result)
        return result

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
