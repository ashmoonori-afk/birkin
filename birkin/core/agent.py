"""Agent class -- core conversation loop with tool dispatch."""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Callable, Optional

from birkin.core.compression import summarize_or_cache
from birkin.core.defaults import DEFAULT_SYSTEM_PROMPT
from birkin.core.models import Message, ToolCall, ToolResult
from birkin.core.providers.base import Provider
from birkin.core.session import Session, SessionStore
from birkin.mcp.adapter import MCPToolAdapter
from birkin.mcp.registry import MCPRegistry
from birkin.tools.base import Tool, ToolContext

if TYPE_CHECKING:
    from birkin.memory.wiki import WikiMemory

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="birkin-tool")

_DEFAULT_MAX_TURNS = 20
_COMPRESS_THRESHOLD = 12
_KEEP_HEAD = 2
_KEEP_TAIL = 16
_CONTEXT_BUDGET_TOKENS = int(os.environ.get("BIRKIN_CONTEXT_BUDGET_TOKENS", "60000"))


class Agent:
    """Stateful agent wrapping a provider, tools, and a session."""

    def __init__(
        self,
        provider: Provider,
        *,
        tools: Optional[list[Tool]] = None,
        session_store: Optional[SessionStore] = None,
        session_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        memory: Optional[WikiMemory] = None,
        max_turns: int = _DEFAULT_MAX_TURNS,
        mcp_registry: Optional[MCPRegistry] = None,
        budget: Optional[Any] = None,
    ) -> None:
        self._provider = provider
        self._budget = budget
        self._tools = tools or []

        # Merge MCP tools into the tool list via adapters
        if mcp_registry is not None:
            for info in mcp_registry.list_all_tools():
                client = mcp_registry.get_client(info.server_name)
                if client is not None:
                    self._tools.append(MCPToolAdapter(info, client))

        self._tool_registry = {t.spec.name: t for t in self._tools}
        self._session_store = session_store or SessionStore()
        self._system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self._memory = memory
        self._max_turns = max_turns

        # LLM-based memory classifier (bilingual Korean/English support)
        # Lazy import to avoid circular dependency: memory → core → memory
        smart_memory = os.environ.get("BIRKIN_SMART_MEMORY", "on").lower()
        if smart_memory != "off" and provider is not None:
            from birkin.memory.classifier import MemoryClassifier

            self._classifier: Optional[Any] = MemoryClassifier(provider)
        else:
            self._classifier = None

        if session_id:
            self._session = self._session_store.load(session_id)
        else:
            self._session = self._session_store.create(
                provider=provider.name,
                model=provider.model,
            )

    @property
    def session(self) -> Session:
        return self._session

    @property
    def session_id(self) -> str:
        return self._session.id

    @property
    def provider(self) -> Provider:
        return self._provider

    def chat(self, user_input: str) -> str:
        """Send a user message and return the assistant's text reply."""
        user_msg = Message(role="user", content=user_input)
        self._session_store.append_message(self._session.id, user_msg)
        response_text = self._run_loop()
        self._auto_save_memory(user_input, response_text)
        return response_text

    async def achat(self, user_input: str) -> str:
        """Async version of chat."""
        user_msg = Message(role="user", content=user_input)
        self._session_store.append_message(self._session.id, user_msg)
        result = await self._run_loop_async()
        self._auto_save_memory(user_input, result)
        return result

    def stream(
        self,
        user_input: str,
        callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Send a user message with streaming deltas.

        Yields deltas via the callback and returns the final assembled response.
        """
        user_msg = Message(role="user", content=user_input)
        self._session_store.append_message(self._session.id, user_msg)

        return self._run_loop(stream_callback=callback)

    async def astream(
        self,
        user_input: str,
        callback: Optional[Callable[[str], None]] = None,
        event_callback: Optional[Callable[[dict], None]] = None,
    ) -> str:
        """Async version of stream."""
        user_msg = Message(role="user", content=user_input)
        self._session_store.append_message(self._session.id, user_msg)
        result = await self._run_loop_async(stream_callback=callback, event_callback=event_callback)
        self._auto_save_memory(user_input, result)
        return result

    def _run_loop(self, stream_callback: Optional[Callable[[str], None]] = None) -> str:
        """Synchronous conversation loop with tool dispatch."""
        turn = 0
        final_text = ""

        while turn < self._max_turns:
            turn += 1

            # Build message list for completion
            messages = self._build_messages()
            tool_schemas = [t.to_provider_schema() for t in self._tools] if self._tools else None

            # Request completion
            response = self._provider.complete(
                messages,
                tools=tool_schemas,
                stream_callback=stream_callback,
            )

            # Create and store assistant message
            assistant_msg = Message(
                role="assistant",
                content=response.content or "",
                tool_calls=[{"id": tc.id, "name": tc.name, "input": tc.input} for tc in (response.tool_calls or [])]
                or None,
            )
            self._session_store.append_message(self._session.id, assistant_msg)

            # Check for tool calls
            if response.tool_calls:
                final_text = ""  # Reset for tool handling
                for tool_call in response.tool_calls:
                    result = self._execute_tool(tool_call)
                    # Store tool result as a message
                    tool_result_msg = Message(
                        role="tool",
                        content=result.content,
                        tool_call_id=result.tool_call_id,
                    )
                    self._session_store.append_message(self._session.id, tool_result_msg)
                # Continue loop to handle tool results
                continue

            # No tool calls — extract text and stop
            final_text = response.content or ""
            break

        return final_text

    async def _run_loop_async(
        self,
        stream_callback: Optional[Callable[[str], None]] = None,
        event_callback: Optional[Callable[[dict], None]] = None,
    ) -> str:
        """Asynchronous conversation loop with tool dispatch."""
        from birkin.observability.logger import StructuredLogger
        from birkin.observability.storage import TraceStorage

        turn = 0
        final_text = ""
        trace = StructuredLogger.start_trace(session_id=self._session.id)

        while turn < self._max_turns:
            turn += 1

            messages = self._build_messages()
            tool_schemas = [t.to_provider_schema() for t in self._tools] if self._tools else None

            if event_callback is not None:
                event_callback({"thinking": True})

            # Budget check before provider call
            if self._budget is not None:
                estimated = sum(len(m.content) for m in messages) // 4
                decision = self._budget.check_before_call(estimated)
                if decision.action == "abort":
                    final_text = f"[Budget exceeded: {decision.reason}]"
                    break
                self._budget.reset_node()

            # Trace: LLM call span
            llm_span = StructuredLogger.start_span(
                trace, "llm_call", provider=self._provider.name, model=self._provider.model
            )

            response = await self._provider.acomplete(
                messages,
                tools=tool_schemas,
                stream_callback=stream_callback,
            )

            StructuredLogger.end_span(
                llm_span,
                tokens_in=response.usage.prompt_tokens if response.usage else 0,
                tokens_out=response.usage.completion_tokens if response.usage else 0,
                status="ok",
            )

            # Record token usage
            if self._budget is not None and response.usage is not None:
                self._budget.record_usage(
                    tokens_in=response.usage.prompt_tokens,
                    tokens_out=response.usage.completion_tokens,
                )

            if event_callback is not None:
                event_callback({"thinking": False})

            # Create and store assistant message
            assistant_msg = Message(
                role="assistant",
                content=response.content or "",
                tool_calls=[{"id": tc.id, "name": tc.name, "input": tc.input} for tc in (response.tool_calls or [])]
                or None,
            )
            self._session_store.append_message(self._session.id, assistant_msg)

            if response.tool_calls:
                final_text = ""
                if event_callback is not None:
                    for tc in response.tool_calls:
                        event_callback(
                            {
                                "tool_call": {
                                    "id": tc.id,
                                    "name": tc.name,
                                    "input": tc.input,
                                }
                            }
                        )
                for tool_call in response.tool_calls:
                    tool_span = StructuredLogger.start_span(trace, f"tool:{tool_call.name}")
                    result = await self._execute_tool_async(tool_call)
                    StructuredLogger.end_span(tool_span, status="ok" if not result.is_error else "error")
                    if event_callback is not None:
                        event_callback(
                            {
                                "tool_result": {
                                    "id": tool_call.id,
                                    "name": tool_call.name,
                                    "output": result.content,
                                    "is_error": result.is_error,
                                }
                            }
                        )
                    tool_result_msg = Message(
                        role="tool",
                        content=result.content,
                        tool_call_id=result.tool_call_id,
                    )
                    self._session_store.append_message(self._session.id, tool_result_msg)
                continue

            final_text = response.content or ""
            break

        # Finalize and persist trace
        StructuredLogger.end_trace(trace)
        try:
            TraceStorage().append(trace)
        except (OSError, RuntimeError):
            pass  # trace storage failure should not break chat

        return final_text

    @property
    def memory(self) -> Optional[WikiMemory]:
        return self._memory

    @staticmethod
    def _pick_category(user_input: str, response: str) -> str:
        """Pick the best wiki category based on content heuristics.

        Uses keyword signals to classify into entities, concepts, or sessions.
        Fast path -- no LLM call required.
        """
        text = (user_input + " " + response).lower()

        entity_signals = [
            "who is",
            "about ",
            "@",
            "company",
            "team",
            "person",
            "organization",
            "project",
            "founded",
            "ceo",
            "cto",
            "employee",
        ]
        concept_signals = [
            "how to",
            "pattern",
            "algorithm",
            "concept",
            "architecture",
            "design",
            "principle",
            "tutorial",
            "explain",
            "difference between",
            "best practice",
        ]

        entity_score = sum(1 for s in entity_signals if s in text)
        concept_score = sum(1 for s in concept_signals if s in text)

        if entity_score > concept_score and entity_score >= 2:
            return "entities"
        elif concept_score > entity_score and concept_score >= 2:
            return "concepts"
        return "sessions"

    @staticmethod
    def _make_slug(user_input: str, session_id: str) -> str:
        """Generate a meaningful slug from user input.

        Extracts the first few meaningful words rather than using only timestamps.
        """
        import re

        # Remove special characters and normalize whitespace
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", "", user_input.lower())
        words = cleaned.split()

        # Filter out very short / stopword-like tokens
        stopwords = frozenset(
            {"a", "an", "the", "is", "are", "was", "were", "be", "to", "of", "and", "or", "in", "on", "it", "i", "my"}
        )
        meaningful = [w for w in words if w not in stopwords and len(w) > 1]

        if meaningful:
            slug_words = meaningful[:4]
            slug_base = "-".join(slug_words)
        else:
            slug_base = "chat"

        # Append short session id to ensure uniqueness
        return f"{slug_base}-{session_id[:6]}"

    # Conversations shorter than this are not worth remembering
    _MIN_MEMORABLE_USER_LEN = 20
    _MIN_MEMORABLE_RESPONSE_LEN = 50

    # Trivial messages that should never be saved
    _TRIVIAL_PATTERNS = frozenset(
        {
            "hi",
            "hello",
            "hey",
            "thanks",
            "thank you",
            "ok",
            "okay",
            "yes",
            "no",
            "bye",
            "good",
            "great",
            "nice",
            "안녕",
            "감사",
            "고마워",
            "네",
            "응",
            "ㅇㅇ",
            "ㄱㅅ",
            "ㅎㅇ",
        }
    )

    def _is_memorable(self, user_input: str, response: str) -> bool:
        """Decide whether a conversation turn is worth saving to memory.

        Filters out greetings, one-word replies, and trivial exchanges
        so memory stays clean and useful.
        """
        # Too short to be meaningful
        if len(user_input.strip()) < self._MIN_MEMORABLE_USER_LEN:
            return False
        if len(response.strip()) < self._MIN_MEMORABLE_RESPONSE_LEN:
            return False

        # Trivial greeting/acknowledgment
        normalized = user_input.strip().lower().rstrip("!?.,")
        if normalized in self._TRIVIAL_PATTERNS:
            return False

        # Must be categorizable (entities or concepts) to be worth saving
        category = self._pick_category(user_input, response)
        if category == "sessions":
            # Only save sessions that are substantive (long enough response)
            return len(response.strip()) >= 200

        return True

    def _auto_save_memory(self, user_input: str, response: str) -> None:
        """Save meaningful conversation turns to wiki memory.

        Tries LLM-based classifier first (bilingual Korean/English).
        Falls back to heuristic classification on classifier error.
        """
        if not self._memory or not response:
            return

        try:
            # --- LLM classifier path (bilingual) ---
            if self._classifier is not None:
                result = self._classifier.classify(user_input, response)

                if result is not None:
                    if not result["should_save"]:
                        return
                    category = result["category"]
                    slug = result["slug"] or self._make_slug(user_input, self._session.id)
                    title = result["title"] or user_input[:80]
                    content = (
                        f"# {category.title()}: {title}\n\n"
                        f"**User:** {user_input[:500]}\n\n"
                        f"**Assistant:** {response[:1000]}\n"
                    )
                    tags = result.get("tags", [])
                    self._memory.ingest(category, slug, content, tags=tags)
                    self._memory.auto_link()
                    return

                # result is None → classifier failed, fall through to heuristic
                logger.debug("Classifier returned None, falling back to heuristic")

            # --- Heuristic fallback path ---
            if not self._is_memorable(user_input, response):
                return
            category = self._pick_category(user_input, response)
            slug = self._make_slug(user_input, self._session.id)
            content = (
                f"# {category.title()}: {user_input[:80]}\n\n"
                f"**User:** {user_input[:500]}\n\n"
                f"**Assistant:** {response[:1000]}\n"
            )
            self._memory.ingest(category, slug, content)
            self._memory.auto_link()
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Auto-save memory failed: %s", exc, exc_info=True)

    def _build_messages(self) -> list[Message]:
        """Assemble the full message list including system prompt and memory."""
        prompt = self._system_prompt or ""

        # Load session messages
        session_messages = self._session_store.get_messages(self._session.id)
        session_messages = self._compress_messages(session_messages, self._provider)

        # 2-tier memory: compact index (always) + wiki_read tool (on-demand)
        # Tier 1: title+tags index (~200t instead of ~5000t full dump)
        # Tier 2: agent calls wiki_read tool when it needs full content
        if self._memory:
            index = self._build_memory_index()
            if index:
                prompt = f"{prompt}\n\n{index}"

        msgs: list[Message] = []
        if prompt:
            msgs.append(Message(role="system", content=prompt))

        # If resuming a session with history, add a context marker so the model
        # knows this is a continuation and should answer the latest message directly.
        if session_messages and len(session_messages) > 1:
            msgs.append(
                Message(
                    role="system",
                    content=(
                        "[Continuing conversation. The messages below are prior context. "
                        "Focus on answering the user's latest message substantively.]"
                    ),
                )
            )

        msgs.extend(session_messages)

        return msgs

    def _build_memory_index(self) -> str:
        """Build a compact title+tags index of memory pages.

        Returns ~200 tokens instead of ~5000 tokens (full page dump).
        The agent uses the wiki_read tool to load full content on demand.
        """
        if not self._memory:
            return ""
        import re as _re

        pages = self._memory.list_pages()
        if not pages:
            return ""

        lines = [
            "## Memory Index",
            "Use the `wiki_read` tool to read full page content when needed.\n",
        ]
        for p in pages:
            cat, slug = p["category"], p["slug"]
            # Extract tags from frontmatter
            content = self._memory.get_page(cat, slug) or ""
            tags = ""
            if content.startswith("---"):
                end = content.find("---", 3)
                if end != -1:
                    fm = content[3:end]
                    tm = _re.search(r"tags:\s*(.+)", fm)
                    if tm:
                        tags = f" [{tm.group(1).strip()}]"
            # Extract first heading as title
            title = slug
            for line in content.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()[:60]
                    break
            lines.append(f"- {cat}/{slug}: {title}{tags}")

        return "\n".join(lines)

    @staticmethod
    def _compress_messages(
        messages: list[Message],
        provider: Provider | None = None,
    ) -> list[Message]:
        """Compress conversation history to prevent context overflow.

        Uses an approximate token count (len // 4) to decide whether
        compression is needed.  When it is, the middle messages are
        summarized via the provider; if summarization fails the method
        falls back to the old head+tail truncation with a marker.
        """
        # Approximate token budget check
        total_chars = sum(len(m.content) for m in messages)
        approx_tokens = total_chars // 4
        if approx_tokens <= _CONTEXT_BUDGET_TOKENS:
            return messages

        if len(messages) <= _COMPRESS_THRESHOLD:
            return messages

        head = messages[:_KEEP_HEAD]
        tail = messages[-_KEEP_TAIL:]
        middle = messages[_KEEP_HEAD : len(messages) - _KEEP_TAIL]

        # Try LLM-based summarization
        summary: str | None = None
        if provider is not None and middle:
            summary = summarize_or_cache(middle, provider)

        if summary is not None:
            summary_msg = Message(
                role="system",
                content=f"[Summary of earlier conversation]\n{summary}",
            )
            return [*head, summary_msg, *tail]

        # Fallback: simple marker
        marker = Message(
            role="system",
            content="[Earlier conversation compressed]",
        )
        return [*head, marker, *tail]

    def _execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool synchronously.

        Uses a dedicated thread with its own event loop to safely bridge
        sync → async, avoiding crashes when an event loop is already running
        (e.g. inside FastAPI).
        """
        tool = self._tool_registry.get(tool_call.name)
        if not tool:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Tool not found: {tool_call.name}",
                is_error=True,
            )

        ctx = ToolContext(session_id=self._session.id)
        try:
            result = _run_async(tool.execute(args=tool_call.input, context=ctx))
            content = result.output if result.success else (result.error or "Unknown error")
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=content,
                is_error=not result.success,
            )
        except (OSError, RuntimeError, ValueError, TimeoutError) as e:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Tool execution failed: {str(e)}",
                is_error=True,
            )

    async def _execute_tool_async(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool asynchronously."""
        tool = self._tool_registry.get(tool_call.name)
        if not tool:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Tool not found: {tool_call.name}",
                is_error=True,
            )

        ctx = ToolContext(session_id=self._session.id)
        try:
            result = await tool.execute(args=tool_call.input, context=ctx)
            content = result.output if result.success else (result.error or "Unknown error")
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=content,
                is_error=not result.success,
            )
        except (OSError, RuntimeError, ValueError, TimeoutError) as e:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Tool execution failed: {str(e)}",
                is_error=True,
            )


def shutdown_executor(wait: bool = True) -> None:
    """Shut down the shared thread-pool executor.

    Called during application shutdown (e.g. FastAPI lifespan) to cleanly
    release worker threads.
    """
    _executor.shutdown(wait=wait)


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from sync context, safe even if a loop is running."""
    try:
        asyncio.get_running_loop()
        # Loop is running (e.g. FastAPI) — offload to the shared pool.
        future = _executor.submit(asyncio.run, coro)
        return future.result()
    except RuntimeError:
        # No running loop — safe to use asyncio.run directly.
        return asyncio.run(coro)
