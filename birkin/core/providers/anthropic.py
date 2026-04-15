"""Anthropic provider implementation."""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

import anthropic

from birkin.core.models import Message, ToolCall
from birkin.core.providers.base import (
    ModelCapabilities,
    Provider,
    ProviderError,
    ProviderErrorKind,
    ProviderResponse,
    TokenUsage,
)

_DEFAULT_MODEL = "claude-opus-4-20250805"

# Model capabilities lookup
_MODEL_CAPS = {
    "claude-opus-4-20250805": ModelCapabilities(context_window=200000),
    "claude-sonnet-4-20250514": ModelCapabilities(context_window=200000),
    "claude-haiku-4-5-20251001": ModelCapabilities(context_window=200000),
}


class AnthropicProvider(Provider):
    """Anthropic Messages API provider."""

    def __init__(self, *, model: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self._model = model or _DEFAULT_MODEL
        api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client = anthropic.Anthropic(api_key=api_key)
        self._async_client = anthropic.AsyncAnthropic(api_key=api_key)

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return self._model

    def capabilities(self) -> ModelCapabilities:
        """Return capabilities for the active model."""
        return _MODEL_CAPS.get(
            self._model,
            ModelCapabilities(context_window=100000),  # Default fallback
        )

    def complete(
        self,
        messages: list[Message],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        stream_callback: Optional[Callable[[Optional[str]], None]] = None,
    ) -> ProviderResponse:
        """Synchronous completion using Anthropic Messages API."""
        try:
            # Convert messages to Anthropic format
            system_msgs = [m for m in messages if m.role == "system"]
            system_str = system_msgs[0].content if system_msgs else None
            conversation_msgs = self._convert_messages(messages)

            # Convert tools to Anthropic format if provided
            anthropic_tools = None
            if tools:
                anthropic_tools = [
                    {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "input_schema": tool.get("parameters", {}),
                    }
                    for tool in tools
                ]

            # Make the API call
            if stream_callback:
                return self._complete_stream(
                    conversation_msgs,
                    system_str,
                    anthropic_tools,
                    stream_callback,
                )
            else:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=4096,
                    system=system_str,
                    messages=conversation_msgs,
                    tools=anthropic_tools,
                )
                return self._parse_response(response)

        except anthropic.RateLimitError as e:
            raise ProviderError(
                f"Anthropic rate limit: {e}",
                ProviderErrorKind.RATE_LIMIT,
                e,
            )
        except anthropic.AuthenticationError as e:
            raise ProviderError(
                f"Anthropic auth error: {e}",
                ProviderErrorKind.AUTH,
                e,
            )
        except anthropic.APIError as e:
            raise ProviderError(
                f"Anthropic API error: {e}",
                ProviderErrorKind.SERVER,
                e,
            )

    async def acomplete(
        self,
        messages: list[Message],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        stream_callback: Optional[Callable[[Optional[str]], None]] = None,
    ) -> ProviderResponse:
        """Asynchronous completion using Anthropic Messages API."""
        try:
            system_msgs = [m for m in messages if m.role == "system"]
            system_str = system_msgs[0].content if system_msgs else None
            conversation_msgs = self._convert_messages(messages)

            anthropic_tools = None
            if tools:
                anthropic_tools = [
                    {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "input_schema": tool.get("parameters", {}),
                    }
                    for tool in tools
                ]

            if stream_callback:
                return await self._acomplete_stream(
                    conversation_msgs,
                    system_str,
                    anthropic_tools,
                    stream_callback,
                )
            else:
                response = await self._async_client.messages.create(
                    model=self._model,
                    max_tokens=4096,
                    system=system_str,
                    messages=conversation_msgs,
                    tools=anthropic_tools,
                )
                return self._parse_response(response)

        except anthropic.RateLimitError as e:
            raise ProviderError(
                f"Anthropic rate limit: {e}",
                ProviderErrorKind.RATE_LIMIT,
                e,
            )
        except anthropic.AuthenticationError as e:
            raise ProviderError(
                f"Anthropic auth error: {e}",
                ProviderErrorKind.AUTH,
                e,
            )
        except anthropic.APIError as e:
            raise ProviderError(
                f"Anthropic API error: {e}",
                ProviderErrorKind.SERVER,
                e,
            )

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert generic messages to Anthropic format."""
        result = []
        for msg in messages:
            if msg.role == "system":
                continue  # System handled separately
            elif msg.role == "tool":
                # Tool result message
                result.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.tool_call_id,
                                "content": msg.content,
                            }
                        ],
                    }
                )
            elif msg.role == "assistant":
                # Assistant message with possible tool calls
                content = [{"type": "text", "text": msg.content}]
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        content.append(
                            {
                                "type": "tool_use",
                                "id": tc.get("id"),
                                "name": tc.get("name"),
                                "input": tc.get("input", {}),
                            }
                        )
                result.append({"role": "assistant", "content": content})
            else:
                # User message
                result.append({"role": msg.role, "content": msg.content})
        return result

    def _parse_response(self, response: Any) -> ProviderResponse:
        """Parse Anthropic API response into ProviderResponse."""
        content = None
        tool_calls = None

        for block in response.content:
            if block.type == "text":
                content = block.text
            elif block.type == "tool_use":
                if tool_calls is None:
                    tool_calls = []
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        input=block.input,
                    )
                )

        usage = TokenUsage(
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
        )

        return ProviderResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            stop_reason=response.stop_reason,
            model=self._model,
        )

    def _complete_stream(
        self,
        messages: list[dict[str, Any]],
        system: Optional[str],
        tools: Optional[list[dict[str, Any]]],
        stream_callback: Callable[[Optional[str]], None],
    ) -> ProviderResponse:
        """Handle streaming completion."""
        accumulated_text = ""

        with self._client.messages.stream(
            model=self._model,
            max_tokens=4096,
            system=system,
            messages=messages,
            tools=tools,
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        accumulated_text += event.delta.text
                        stream_callback(event.delta.text)
                elif event.type == "content_block_start":
                    pass

        stream_callback(None)  # Signal end

        # Parse the final response to extract tool calls
        response = stream.get_final_message()
        parsed = self._parse_response(response)

        return ProviderResponse(
            content=accumulated_text if accumulated_text else None,
            tool_calls=parsed.tool_calls,
            usage=parsed.usage,
            stop_reason=parsed.stop_reason,
            model=self._model,
        )

    async def _acomplete_stream(
        self,
        messages: list[dict[str, Any]],
        system: Optional[str],
        tools: Optional[list[dict[str, Any]]],
        stream_callback: Callable[[Optional[str]], None],
    ) -> ProviderResponse:
        """Handle async streaming completion."""
        accumulated_text = ""

        async with self._async_client.messages.stream(
            model=self._model,
            max_tokens=4096,
            system=system,
            messages=messages,
            tools=tools,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        accumulated_text += event.delta.text
                        stream_callback(event.delta.text)

        stream_callback(None)

        response = await stream.get_final_message()
        parsed = self._parse_response(response)

        return ProviderResponse(
            content=accumulated_text if accumulated_text else None,
            tool_calls=parsed.tool_calls,
            usage=parsed.usage,
            stop_reason=parsed.stop_reason,
            model=self._model,
        )
