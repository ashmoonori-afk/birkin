"""Local CLI provider — shells out to claude or codex commands."""

from __future__ import annotations

import asyncio
import shutil
from typing import Any, Callable, Optional

from birkin.core.errors import ProviderError, ProviderErrorKind
from birkin.core.models import Message
from birkin.core.providers.base import (
    ModelCapabilities,
    Provider,
    ProviderResponse,
    TokenUsage,
)


class LocalCLIProvider(Provider):
    """Provider that delegates to a local CLI tool (claude or codex).

    Requires no API key — uses whatever authentication the CLI
    already has configured (e.g., `claude` uses the user's session).
    """

    def __init__(
        self,
        *,
        cli: str = "claude",
        model: Optional[str] = None,
    ) -> None:
        self._cli = cli  # "claude" or "codex"
        self._model = model or f"{cli}-local"

        binary = shutil.which(cli)
        if not binary:
            raise ProviderError(
                f"CLI tool '{cli}' not found in PATH. Install it first.",
                ProviderErrorKind.AUTH,
            )
        self._binary = binary

    @property
    def name(self) -> str:
        return f"{self._cli}-cli"

    @property
    def model(self) -> str:
        return self._model

    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            context_window=100000,
            supports_tools=False,
            supports_streaming=False,
        )

    def complete(
        self,
        messages: list[Message],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        stream_callback: Optional[Callable[[Optional[str]], None]] = None,
    ) -> ProviderResponse:
        """Run the CLI synchronously with the last user message."""
        prompt = self._extract_prompt(messages)

        try:
            import subprocess

            cmd = self._build_command(prompt)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                error_text = result.stderr.strip() or f"CLI exited with code {result.returncode}"
                raise ProviderError(
                    f"{self._cli} error: {error_text}",
                    ProviderErrorKind.SERVER,
                )

            output = result.stdout.strip()
            if stream_callback:
                stream_callback(output)
                stream_callback(None)

            return ProviderResponse(
                content=output,
                tool_calls=None,
                usage=TokenUsage(prompt_tokens=0, completion_tokens=0),
                stop_reason="stop",
                model=self._model,
            )

        except subprocess.TimeoutExpired:
            raise ProviderError(
                f"{self._cli} timed out after 120 seconds",
                ProviderErrorKind.SERVER,
            )
        except FileNotFoundError:
            raise ProviderError(
                f"CLI tool '{self._cli}' not found",
                ProviderErrorKind.AUTH,
            )

    async def acomplete(
        self,
        messages: list[Message],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        stream_callback: Optional[Callable[[Optional[str]], None]] = None,
    ) -> ProviderResponse:
        """Async version — runs CLI in a subprocess."""
        prompt = self._extract_prompt(messages)
        cmd = self._build_command(prompt)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

            if proc.returncode != 0:
                error_text = stderr.decode().strip() or f"CLI exited with code {proc.returncode}"
                raise ProviderError(
                    f"{self._cli} error: {error_text}",
                    ProviderErrorKind.SERVER,
                )

            output = stdout.decode().strip()
            if stream_callback:
                stream_callback(output)
                stream_callback(None)

            return ProviderResponse(
                content=output,
                tool_calls=None,
                usage=TokenUsage(prompt_tokens=0, completion_tokens=0),
                stop_reason="stop",
                model=self._model,
            )

        except asyncio.TimeoutError:
            raise ProviderError(
                f"{self._cli} timed out after 120 seconds",
                ProviderErrorKind.SERVER,
            )

    def _extract_prompt(self, messages: list[Message]) -> str:
        """Get the last user message as the prompt."""
        for msg in reversed(messages):
            if msg.role == "user":
                return msg.content
        return ""

    def _build_command(self, prompt: str) -> list[str]:
        """Build the CLI command."""
        if self._cli == "claude":
            return [self._binary, "-p", prompt]
        elif self._cli == "codex":
            return [self._binary, "-q", prompt]
        else:
            return [self._binary, prompt]
