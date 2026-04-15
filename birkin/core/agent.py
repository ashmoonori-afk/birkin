"""Agent class -- core conversation loop with tool dispatch."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from birkin.core.defaults import DEFAULT_SYSTEM_PROMPT
from birkin.core.models import Message, ToolCall, ToolResult
from birkin.core.providers.base import Provider, ProviderResponse
from birkin.core.session import Session, SessionStore
from birkin.memory.wiki import WikiMemory
from birkin.tools.base import Tool

_DEFAULT_MAX_TURNS = 20


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
    ) -> None:
        self._provider = provider
        self._tools = tools or []
        self._tool_registry = {t.spec.name: t for t in self._tools}
        self._session_store = session_store or SessionStore()
        self._system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self._memory = memory
        self._max_turns = max_turns

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
        """Send a user message and return the assistant's text reply.

        This is the synchronous, non-streaming path used by the CLI REPL.
        Implements the conversation loop with tool dispatch.
        """
        # Append user message
        user_msg = Message(role="user", content=user_input)
        self._session_store.append_message(self._session.id, user_msg)

        # Run the conversation loop
        response_text = self._run_loop()
        return response_text

    async def achat(self, user_input: str) -> str:
        """Async version of chat."""
        user_msg = Message(role="user", content=user_input)
        self._session_store.append_message(self._session.id, user_msg)
        return await self._run_loop_async()

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
    ) -> str:
        """Async version of stream."""
        user_msg = Message(role="user", content=user_input)
        self._session_store.append_message(self._session.id, user_msg)

        return await self._run_loop_async(stream_callback=callback)

    def _run_loop(
        self, stream_callback: Optional[Callable[[str], None]] = None
    ) -> str:
        """Synchronous conversation loop with tool dispatch."""
        turn = 0
        final_text = ""

        while turn < self._max_turns:
            turn += 1

            # Build message list for completion
            messages = self._build_messages()
            tool_schemas = (
                [t.to_provider_schema() for t in self._tools] if self._tools else None
            )

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
                tool_calls=[
                    {"id": tc.id, "name": tc.name, "input": tc.input}
                    for tc in (response.tool_calls or [])
                ] or None,
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
                    self._session_store.append_message(
                        self._session.id, tool_result_msg
                    )
                # Continue loop to handle tool results
                continue

            # No tool calls — extract text and stop
            final_text = response.content or ""
            break

        return final_text

    async def _run_loop_async(
        self, stream_callback: Optional[Callable[[str], None]] = None
    ) -> str:
        """Asynchronous conversation loop with tool dispatch."""
        turn = 0
        final_text = ""

        while turn < self._max_turns:
            turn += 1

            messages = self._build_messages()
            tool_schemas = (
                [t.to_provider_schema() for t in self._tools] if self._tools else None
            )

            response = await self._provider.acomplete(
                messages,
                tools=tool_schemas,
                stream_callback=stream_callback,
            )

            # Create and store assistant message
            assistant_msg = Message(
                role="assistant",
                content=response.content or "",
                tool_calls=[
                    {"id": tc.id, "name": tc.name, "input": tc.input}
                    for tc in (response.tool_calls or [])
                ] or None,
            )
            self._session_store.append_message(self._session.id, assistant_msg)

            if response.tool_calls:
                final_text = ""
                for tool_call in response.tool_calls:
                    result = await self._execute_tool_async(tool_call)
                    tool_result_msg = Message(
                        role="tool",
                        content=result.content,
                        tool_call_id=result.tool_call_id,
                    )
                    self._session_store.append_message(
                        self._session.id, tool_result_msg
                    )
                continue

            final_text = response.content or ""
            break

        return final_text

    @property
    def memory(self) -> Optional[WikiMemory]:
        return self._memory

    def _build_messages(self) -> list[Message]:
        """Assemble the full message list including system prompt and memory."""
        prompt = self._system_prompt or ""

        # Append memory context when a WikiMemory backend is attached
        if self._memory:
            memory_ctx = self._memory.build_context()
            if memory_ctx:
                prompt = f"{prompt}\n\n{memory_ctx}"

        msgs: list[Message] = []
        if prompt:
            msgs.append(Message(role="system", content=prompt))

        # Load messages from session store
        session_messages = self._session_store.get_messages(self._session.id)
        msgs.extend(session_messages)

        return msgs

    def _execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool synchronously."""
        tool = self._tool_registry.get(tool_call.name)
        if not tool:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Tool not found: {tool_call.name}",
                is_error=True,
            )

        try:
            # Execute synchronously (blocking)
            result = asyncio.run(tool.execute(**tool_call.input))
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=result,
                is_error=False,
            )
        except Exception as e:
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

        try:
            result = await tool.execute(**tool_call.input)
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=result,
                is_error=False,
            )
        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Tool execution failed: {str(e)}",
                is_error=True,
            )
