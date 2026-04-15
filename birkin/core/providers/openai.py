"""OpenAI provider implementation."""

from __future__ import annotations

import os
from typing import Any, Callable

from openai import AsyncOpenAI, OpenAI

from birkin.core.models import Message, ToolCall
from birkin.core.providers.base import (
    ModelCapabilities,
    ProviderError,
    ProviderErrorKind,
    ProviderResponse,
    TokenUsage,
)
from birkin.core.providers.base import Provider

_DEFAULT_MODEL = "gpt-4o"

# Model capabilities
_MODEL_CAPS = {
    "gpt-4o": ModelCapabilities(context_window=128000),
    "gpt-4-turbo": ModelCapabilities(context_window=128000),
    "gpt-4": ModelCapabilities(context_window=8192),
    "gpt-3.5-turbo": ModelCapabilities(context_window=4096),
}


class OpenAIProvider(Provider):
    """OpenAI Chat Completions provider (also supports OpenRouter and compatible servers)."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model = model or _DEFAULT_MODEL
        api_key = api_key or os.getenv("OPENAI_API_KEY")

        # Detect OpenRouter
        if base_url is None and self._model.startswith("openrouter/"):
            base_url = "https://openrouter.ai/api/v1"

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._async_client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    @property
    def name(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    def capabilities(self) -> ModelCapabilities:
        """Return capabilities for the active model."""
        return _MODEL_CAPS.get(
            self._model,
            ModelCapabilities(context_window=128000),  # Default
        )

    def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        stream_callback: Callable[[str | None], None] | None = None,
    ) -> ProviderResponse:
        """Synchronous completion using OpenAI Chat Completions API."""
        try:
            openai_messages = self._convert_messages(messages)

            # Prepare tool_choice parameter
            tool_choice = "auto" if tools else None

            if stream_callback:
                return self._complete_stream(
                    openai_messages,
                    tools,
                    tool_choice,
                    stream_callback,
                )
            else:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=openai_messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=1.0,
                )
                return self._parse_response(response)

        except Exception as e:
            # Categorize OpenAI errors
            error_name = type(e).__name__
            if "rate" in str(e).lower():
                kind = ProviderErrorKind.RATE_LIMIT
            elif "auth" in error_name.lower():
                kind = ProviderErrorKind.AUTH
            elif "context" in str(e).lower():
                kind = ProviderErrorKind.CONTEXT_OVERFLOW
            else:
                kind = ProviderErrorKind.SERVER

            raise ProviderError(
                f"OpenAI API error: {e}",
                kind,
                e,
            )

    async def acomplete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        stream_callback: Callable[[str | None], None] | None = None,
    ) -> ProviderResponse:
        """Asynchronous completion using OpenAI Chat Completions API."""
        try:
            openai_messages = self._convert_messages(messages)
            tool_choice = "auto" if tools else None

            if stream_callback:
                return await self._acomplete_stream(
                    openai_messages,
                    tools,
                    tool_choice,
                    stream_callback,
                )
            else:
                response = await self._async_client.chat.completions.create(
                    model=self._model,
                    messages=openai_messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=1.0,
                )
                return self._parse_response(response)

        except Exception as e:
            error_name = type(e).__name__
            if "rate" in str(e).lower():
                kind = ProviderErrorKind.RATE_LIMIT
            elif "auth" in error_name.lower():
                kind = ProviderErrorKind.AUTH
            elif "context" in str(e).lower():
                kind = ProviderErrorKind.CONTEXT_OVERFLOW
            else:
                kind = ProviderErrorKind.SERVER

            raise ProviderError(
                f"OpenAI API error: {e}",
                kind,
                e,
            )

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert generic messages to OpenAI Chat Completions format."""
        result = []
        for msg in messages:
            if msg.role == "system":
                result.append({"role": "system", "content": msg.content})
            elif msg.role == "user":
                result.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                content = msg.content
                tool_calls = None
                if msg.tool_calls:
                    tool_calls = [
                        {
                            "id": tc.get("id"),
                            "type": "function",
                            "function": {
                                "name": tc.get("function_name"),
                                "arguments": str(tc.get("arguments", {})),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                result.append(
                    {
                        "role": "assistant",
                        "content": content,
                        "tool_calls": tool_calls,
                    }
                    if tool_calls
                    else {"role": "assistant", "content": content}
                )
            elif msg.role == "tool":
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id,
                        "content": msg.content,
                    }
                )
        return result

    def _parse_response(self, response: Any) -> ProviderResponse:
        """Parse OpenAI API response into ProviderResponse."""
        choice = response.choices[0]
        content = choice.message.content

        tool_calls = None
        if choice.message.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    input=tc.function.arguments,
                )
                for tc in choice.message.tool_calls
            ]

        usage = TokenUsage(
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )

        return ProviderResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            stop_reason=choice.finish_reason,
            model=self._model,
        )

    def _complete_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        tool_choice: str | None,
        stream_callback: Callable[[str | None], None],
    ) -> ProviderResponse:
        """Handle streaming completion."""
        accumulated_text = ""

        stream = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=1.0,
            stream=True,
        )

        for chunk in stream:
            if chunk.choices[0].delta.content:
                accumulated_text += chunk.choices[0].delta.content
                stream_callback(chunk.choices[0].delta.content)

        stream_callback(None)

        usage = TokenUsage(
            prompt_tokens=0,  # Streaming doesn't provide usage in deltas
            completion_tokens=0,
        )

        return ProviderResponse(
            content=accumulated_text if accumulated_text else None,
            tool_calls=None,
            usage=usage,
            stop_reason="stop",
            model=self._model,
        )

    async def _acomplete_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        tool_choice: str | None,
        stream_callback: Callable[[str | None], None],
    ) -> ProviderResponse:
        """Handle async streaming completion."""
        accumulated_text = ""

        stream = await self._async_client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=1.0,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                accumulated_text += chunk.choices[0].delta.content
                stream_callback(chunk.choices[0].delta.content)

        stream_callback(None)

        usage = TokenUsage(
            prompt_tokens=0,
            completion_tokens=0,
        )

        return ProviderResponse(
            content=accumulated_text if accumulated_text else None,
            tool_calls=None,
            usage=usage,
            stop_reason="stop",
            model=self._model,
        )
